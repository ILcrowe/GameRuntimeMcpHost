using System;
using System.Collections.Concurrent;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

namespace lLCroweTool.GameRuntimeMcpHost
{
    /// <summary>
    /// Minimal game-owned Unity adapter for GameRuntimeMcpHost.
    /// Attach it to an explicit RuntimeServices object in a boot scene or prefab.
    /// </summary>
    public sealed class UnityRuntimeMcpSampleBridge : MonoBehaviour
    {
        [Serializable]
        private sealed class SessionDescriptor
        {
            public int protocolVersion = 1;
            public string endpoint;
            public string token;
            public string tokenHeader = TokenHeader;
            public string rpcPath = RpcPath;
            public string product;
            public int processId;
        }

        [Serializable]
        private sealed class RuntimeRpcRequest
        {
            public int protocol;
            public string command;
            public SamplePayload payload;
        }

        [Serializable]
        private sealed class SamplePayload
        {
            public string message;
        }

        [Serializable]
        private sealed class RuntimeRpcResponse
        {
            public bool ok;
            public SampleResult result;
            public RuntimeRpcError error;
        }

        [Serializable]
        private sealed class SampleResult
        {
            public string product;
            public string unityVersion;
            public bool isPlaying;
            public int processId;
            public int frameCount;
            public string message;
        }

        [Serializable]
        private sealed class RuntimeRpcError
        {
            public string code;
            public string message;
        }

        private sealed class PendingRequest
        {
            public string RequestJson;
            public readonly TaskCompletionSource<HttpReply> Completion =
                new TaskCompletionSource<HttpReply>(TaskCreationOptions.RunContinuationsAsynchronously);

            private int state;

            public bool TryBeginDispatch()
            {
                return Interlocked.CompareExchange(ref state, 1, 0) == 0;
            }

            public bool TryAbandon()
            {
                return Interlocked.CompareExchange(ref state, 2, 0) == 0;
            }

            public void Complete(in HttpReply reply)
            {
                Completion.TrySetResult(reply);
                Volatile.Write(ref state, 3);
            }
        }

        private readonly struct HttpReply
        {
            public readonly int StatusCode;
            public readonly string Body;

            public HttpReply(int statusCode, string body)
            {
                StatusCode = statusCode;
                Body = body;
            }
        }

        private const int ProtocolVersion = 1;
        private const int DefaultPort = 18761;
        private const string DefaultSessionFileName = "unity-runtime-mcp-sample.json";
        private const string TokenHeader = "X-Game-Runtime-Token";
        private const string RpcPath = "/rpc";

        [Header("Runtime MCP Sample")]
        [SerializeField] private bool runtimeMcpEnabled = true;
        [SerializeField, Min(1)] private int preferredPort = DefaultPort;
        [SerializeField, Min(1)] private int portSearchCount = 8;
        [SerializeField, Min(1024)] private int maxRequestBytes = 65536;
        [SerializeField, Min(1)] private int requestTimeoutSeconds = 10;
        [SerializeField, Min(1)] private int maxRequestsPerFrame = 8;
        [SerializeField] private string sessionFileName = DefaultSessionFileName;

        private readonly ConcurrentQueue<PendingRequest> requestQueue =
            new ConcurrentQueue<PendingRequest>();
        private readonly ConcurrentQueue<string> warningQueue =
            new ConcurrentQueue<string>();

        private HttpListener listener;
        private Thread listenerThread;
        private string sessionToken;
        private string sessionPath;
        private volatile bool stopping;
        private bool bridgeStarted;
        private bool previousRunInBackground;
        private int activePort;

        /// <summary>Returns true while the loopback HTTP listener is active.</summary>
        public bool IsListenerRunning => listener != null && listener.IsListening;

        /// <summary>Returns the selected loopback port, or zero while stopped.</summary>
        public int ActivePort => activePort;

        /// <summary>Returns the current session descriptor path, or an empty string while stopped.</summary>
        public string SessionPath => sessionPath;

        private void OnEnable()
        {
            if (!Application.isPlaying || !runtimeMcpEnabled)
            {
                return;
            }

            StartBridge();
        }

        private void Update()
        {
            while (warningQueue.TryDequeue(out string warning))
            {
                Debug.LogWarning($"[RuntimeMCP Sample] {warning}", this);
            }

            int requestBudget = Mathf.Max(1, maxRequestsPerFrame);
            while (requestBudget-- > 0 && requestQueue.TryDequeue(out PendingRequest pending))
            {
                if (!pending.TryBeginDispatch())
                {
                    continue;
                }

                HttpReply reply;
                try
                {
                    reply = Dispatch(pending.RequestJson);
                }
                catch (Exception exception)
                {
                    reply = JsonReply(
                        200,
                        Error("dispatch_failed", exception.Message));
                }

                pending.Complete(reply);
            }
        }

        private void OnDisable()
        {
            StopBridge();
        }

        /// <summary>
        /// Starts the loopback listener and writes a per-run session descriptor.
        /// </summary>
        /// <returns>True when the listener and descriptor are ready.</returns>
        public bool StartBridge()
        {
            if (bridgeStarted)
            {
                return IsListenerRunning;
            }

            if (!Application.isPlaying)
            {
                Debug.LogWarning("[RuntimeMCP Sample] StartBridge requires Play Mode.", this);
                return false;
            }

            previousRunInBackground = Application.runInBackground;
            Application.runInBackground = true;
            bridgeStarted = true;
            stopping = false;
            sessionToken = Guid.NewGuid().ToString("N");

            if (!TryStartListener(out string endpoint, out string failure))
            {
                StopBridge();
                Debug.LogWarning($"[RuntimeMCP Sample] {failure}", this);
                return false;
            }

            try
            {
                WriteSessionDescriptor(endpoint);
            }
            catch (Exception exception)
            {
                StopBridge();
                Debug.LogWarning(
                    $"[RuntimeMCP Sample] Could not write the session descriptor: {exception.Message}",
                    this);
                return false;
            }

            listenerThread = new Thread(ListenLoop)
            {
                IsBackground = true,
                Name = "UnityRuntimeMcpSampleListener"
            };
            listenerThread.Start();
            Debug.Log($"[RuntimeMCP Sample] Ready. Session: {sessionPath}", this);
            return true;
        }

        /// <summary>
        /// Stops the listener, releases waiting calls, and removes this run's descriptor.
        /// </summary>
        public void StopBridge()
        {
            if (!bridgeStarted)
            {
                return;
            }

            stopping = true;
            try
            {
                listener?.Stop();
            }
            catch (ObjectDisposedException)
            {
                // The listener was already closed by a failed start or another stop path.
            }

            while (requestQueue.TryDequeue(out PendingRequest pending))
            {
                if (pending.TryAbandon())
                {
                    pending.Complete(
                        ErrorReply(503, "runtime_stopping", "The Unity runtime is stopping."));
                }
            }

            if (listenerThread != null && listenerThread.IsAlive)
            {
                listenerThread.Join(500);
            }

            listenerThread = null;
            listener?.Close();
            listener = null;
            DeleteSessionDescriptor();

            Application.runInBackground = previousRunInBackground;
            bridgeStarted = false;
            activePort = 0;
            sessionToken = string.Empty;
            stopping = false;
        }

        private bool TryStartListener(out string endpoint, out string failure)
        {
            endpoint = string.Empty;
            failure = string.Empty;
            Exception lastException = null;
            int firstPort = Mathf.Clamp(preferredPort, 1, 65535);
            int attempts = Mathf.Max(1, portSearchCount);

            for (int offset = 0; offset < attempts && firstPort + offset <= 65535; offset++)
            {
                activePort = firstPort + offset;
                endpoint = $"http://127.0.0.1:{activePort}/";
                listener = new HttpListener();
                listener.Prefixes.Add(endpoint);

                try
                {
                    listener.Start();
                    return true;
                }
                catch (Exception exception) when (
                    exception is HttpListenerException ||
                    exception is InvalidOperationException)
                {
                    lastException = exception;
                    listener.Close();
                    listener = null;
                }
            }

            failure = $"No loopback port was available after {attempts} attempts: {lastException?.Message}";
            activePort = 0;
            endpoint = string.Empty;
            return false;
        }

        private void WriteSessionDescriptor(string endpoint)
        {
            string safeFileName = Path.GetFileName(sessionFileName);
            if (string.IsNullOrWhiteSpace(safeFileName))
            {
                safeFileName = DefaultSessionFileName;
            }

            sessionPath = Path.Combine(Application.persistentDataPath, safeFileName);
            string temporaryPath = sessionPath + "." + Guid.NewGuid().ToString("N") + ".tmp";
            var descriptor = new SessionDescriptor
            {
                endpoint = endpoint,
                token = sessionToken,
                product = Application.productName,
                processId = System.Diagnostics.Process.GetCurrentProcess().Id
            };
            string json = JsonUtility.ToJson(descriptor, true);

            try
            {
                File.WriteAllText(temporaryPath, json, new UTF8Encoding(false));
                if (File.Exists(sessionPath))
                {
                    try
                    {
                        File.Replace(temporaryPath, sessionPath, null);
                        return;
                    }
                    catch (PlatformNotSupportedException)
                    {
                        File.Delete(sessionPath);
                    }
                    catch (IOException)
                    {
                        File.Delete(sessionPath);
                    }
                }

                File.Move(temporaryPath, sessionPath);
            }
            finally
            {
                if (File.Exists(temporaryPath))
                {
                    File.Delete(temporaryPath);
                }
            }
        }

        private void DeleteSessionDescriptor()
        {
            if (!string.IsNullOrEmpty(sessionPath) && File.Exists(sessionPath))
            {
                try
                {
                    File.Delete(sessionPath);
                }
                catch (IOException exception)
                {
                    Debug.LogWarning(
                        $"[RuntimeMCP Sample] Could not remove the session descriptor: {exception.Message}",
                        this);
                }
                catch (UnauthorizedAccessException exception)
                {
                    Debug.LogWarning(
                        $"[RuntimeMCP Sample] Could not remove the session descriptor: {exception.Message}",
                        this);
                }
            }

            sessionPath = string.Empty;
        }

        private void ListenLoop()
        {
            while (!stopping && listener != null && listener.IsListening)
            {
                try
                {
                    HandleHttp(listener.GetContext());
                }
                catch (HttpListenerException)
                {
                    if (!stopping)
                    {
                        warningQueue.Enqueue("The loopback listener stopped unexpectedly.");
                    }
                }
                catch (ObjectDisposedException)
                {
                    return;
                }
                catch (Exception exception)
                {
                    if (!stopping)
                    {
                        warningQueue.Enqueue($"Listener error: {exception.Message}");
                    }
                }
            }
        }

        private void HandleHttp(HttpListenerContext context)
        {
            HttpListenerRequest request = context.Request;
            if (!string.Equals(request.HttpMethod, "POST", StringComparison.OrdinalIgnoreCase) ||
                request.Url == null ||
                !string.Equals(request.Url.AbsolutePath, RpcPath, StringComparison.Ordinal))
            {
                WriteHttp(context.Response, ErrorReply(404, "not_found", "Use POST /rpc."));
                return;
            }

            if (!string.Equals(request.Headers[TokenHeader], sessionToken, StringComparison.Ordinal))
            {
                WriteHttp(
                    context.Response,
                    ErrorReply(401, "unauthorized", "The runtime session token is missing or invalid."));
                return;
            }

            int requestLimit = Math.Max(1024, maxRequestBytes);
            if (!TryReadRequestBody(request, requestLimit, out string requestJson))
            {
                WriteHttp(
                    context.Response,
                    ErrorReply(413, "request_too_large", $"Request body exceeds {requestLimit} bytes."));
                return;
            }

            var pending = new PendingRequest { RequestJson = requestJson };
            requestQueue.Enqueue(pending);
            TimeSpan timeout = TimeSpan.FromSeconds(Math.Max(1, requestTimeoutSeconds));
            if (!pending.Completion.Task.Wait(timeout))
            {
                pending.TryAbandon();
                WriteHttp(
                    context.Response,
                    ErrorReply(504, "main_thread_timeout", "Unity did not service the request in time."));
                return;
            }

            WriteHttp(context.Response, pending.Completion.Task.Result);
        }

        private static bool TryReadRequestBody(
            HttpListenerRequest request,
            int maxBytes,
            out string body)
        {
            body = string.Empty;
            if (request.ContentLength64 > maxBytes)
            {
                return false;
            }

            using var memoryStream = new MemoryStream();
            byte[] buffer = new byte[4096];
            int totalBytes = 0;
            while (true)
            {
                int readBytes = request.InputStream.Read(buffer, 0, buffer.Length);
                if (readBytes <= 0)
                {
                    break;
                }

                totalBytes += readBytes;
                if (totalBytes > maxBytes)
                {
                    return false;
                }

                memoryStream.Write(buffer, 0, readBytes);
            }

            Encoding encoding = request.ContentEncoding ?? Encoding.UTF8;
            body = encoding.GetString(memoryStream.ToArray());
            return true;
        }

        private HttpReply Dispatch(string requestJson)
        {
            RuntimeRpcRequest request;
            try
            {
                request = JsonUtility.FromJson<RuntimeRpcRequest>(requestJson);
            }
            catch (ArgumentException exception)
            {
                return JsonReply(200, Error("invalid_json", exception.Message));
            }

            if (request == null || string.IsNullOrWhiteSpace(request.command))
            {
                return JsonReply(200, Error("invalid_request", "A command is required."));
            }

            if (request.protocol != ProtocolVersion)
            {
                return JsonReply(
                    200,
                    Error("unsupported_protocol", $"Expected protocol {ProtocolVersion}."));
            }

            switch (request.command)
            {
                case "runtime.status":
                    return JsonReply(
                        200,
                        Ok(new SampleResult
                        {
                            product = Application.productName,
                            unityVersion = Application.unityVersion,
                            isPlaying = Application.isPlaying,
                            processId = System.Diagnostics.Process.GetCurrentProcess().Id,
                            frameCount = Time.frameCount
                        }));
                case "sample.echo":
                    return JsonReply(
                        200,
                        Ok(new SampleResult
                        {
                            message = request.payload?.message ?? string.Empty
                        }));
                default:
                    return JsonReply(
                        200,
                        Error("unknown_command", $"Unknown command: {request.command}"));
            }
        }

        private static RuntimeRpcResponse Ok(SampleResult result)
        {
            return new RuntimeRpcResponse
            {
                ok = true,
                result = result
            };
        }

        private static RuntimeRpcResponse Error(string code, string message)
        {
            return new RuntimeRpcResponse
            {
                ok = false,
                error = new RuntimeRpcError
                {
                    code = code,
                    message = message
                }
            };
        }

        private static HttpReply JsonReply(int statusCode, RuntimeRpcResponse response)
        {
            return new HttpReply(statusCode, JsonUtility.ToJson(response));
        }

        private static HttpReply ErrorReply(int statusCode, string code, string message)
        {
            string body =
                $"{{\"ok\":false,\"error\":{{\"code\":\"{EscapeJsonString(code)}\"," +
                $"\"message\":\"{EscapeJsonString(message)}\"}}}}";
            return new HttpReply(statusCode, body);
        }

        private static string EscapeJsonString(string value)
        {
            if (string.IsNullOrEmpty(value))
            {
                return string.Empty;
            }

            var builder = new StringBuilder(value.Length + 8);
            foreach (char character in value)
            {
                switch (character)
                {
                    case '\"':
                        builder.Append("\\\"");
                        break;
                    case '\\':
                        builder.Append("\\\\");
                        break;
                    case '\b':
                        builder.Append("\\b");
                        break;
                    case '\f':
                        builder.Append("\\f");
                        break;
                    case '\n':
                        builder.Append("\\n");
                        break;
                    case '\r':
                        builder.Append("\\r");
                        break;
                    case '\t':
                        builder.Append("\\t");
                        break;
                    default:
                        if (char.IsControl(character))
                        {
                            builder.Append("\\u");
                            builder.Append(((int)character).ToString("x4"));
                        }
                        else
                        {
                            builder.Append(character);
                        }
                        break;
                }
            }

            return builder.ToString();
        }

        private static void WriteHttp(HttpListenerResponse response, in HttpReply reply)
        {
            byte[] bytes = Encoding.UTF8.GetBytes(reply.Body);
            response.StatusCode = reply.StatusCode;
            response.ContentType = "application/json; charset=utf-8";
            response.ContentLength64 = bytes.Length;
            using Stream outputStream = response.OutputStream;
            outputStream.Write(bytes, 0, bytes.Length);
        }
    }
}
