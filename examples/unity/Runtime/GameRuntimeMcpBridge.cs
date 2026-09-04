using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace GameRuntimeMcp
{
    /// <summary>
    /// GameRuntimeMcpHost와 실행 중인 Unity Player를 연결하는 로컬 RPC 브리지입니다.
    /// MCP는 Python Host가 담당하고, 이 컴포넌트는 세션·인증·메인 스레드 디스패치만 담당합니다.
    /// </summary>
    [DefaultExecutionOrder(-1000)]
    [DisallowMultipleComponent]
    public sealed class GameRuntimeMcpBridge : MonoBehaviour
    {
        public delegate object RuntimeCommandHandler(string requestJson);

        [Serializable]
        private sealed class SessionDescriptor
        {
            public int protocolVersion = 1;
            public string endpoint;
            public string token;
            public string tokenHeader = TokenHeader;
            public string rpcPath = DefaultRpcPath;
            public string product;
            public int processId;
        }

        [Serializable]
        private sealed class RequestHeader
        {
            public int protocol;
            public string command;
        }

        [Serializable]
        public sealed class RuntimeStatusResult
        {
            public string product;
            public string unityVersion;
            public int processId;
            public int frameCount;
            public string sceneName;
            public bool isPaused;
        }

        private sealed class PendingRequest
        {
            public string json;
            public readonly TaskCompletionSource<HttpReply> completion =
                new TaskCompletionSource<HttpReply>(
                    TaskCreationOptions.RunContinuationsAsynchronously);

            // 0 queued, 1 dispatching, 2 abandoned, 3 completed
            private int state;

            public bool TryBegin()
            {
                return Interlocked.CompareExchange(ref state, 1, 0) == 0;
            }

            public bool TryAbandon()
            {
                return Interlocked.CompareExchange(ref state, 2, 0) == 0;
            }

            public void Complete(HttpReply reply)
            {
                completion.TrySetResult(reply);
                Volatile.Write(ref state, 3);
            }
        }

        private readonly struct HttpReply
        {
            public readonly int statusCode;
            public readonly string body;

            public HttpReply(int statusCode, string body)
            {
                this.statusCode = statusCode;
                this.body = body;
            }
        }

        private const int ProtocolVersion = 1;
        private const int DefaultPort = 18765;
        private const string DefaultSessionFile = "game-runtime-mcp-session.json";
        private const string DefaultRpcPath = "/rpc";
        private const string TokenHeader = "X-Game-Runtime-Token";
        private const string RuntimeStatusCommand = "runtime.status";

        public static GameRuntimeMcpBridge Instance { get; private set; }

        [Header("Session")]
        [SerializeField] private bool runtimeMcpEnabled = true;
        [SerializeField] private string sessionProductName = "UnityGameRuntime";
        [SerializeField] private string sessionFileName = DefaultSessionFile;
        [SerializeField, Min(1)] private int preferredPort = DefaultPort;
        [SerializeField, Min(1)] private int portSearchCount = 10;
        [SerializeField] private string rpcPath = DefaultRpcPath;

        [Header("Limits")]
        [SerializeField, Min(1024)] private int maxRequestBytes = 65536;
        [SerializeField, Min(1)] private int requestTimeoutSeconds = 10;
        [SerializeField, Min(1)] private int maxRequestsPerFrame = 8;

        private readonly ConcurrentQueue<PendingRequest> requests =
            new ConcurrentQueue<PendingRequest>();
        private readonly ConcurrentQueue<string> warnings =
            new ConcurrentQueue<string>();
        private readonly Dictionary<string, RuntimeCommandHandler> handlers =
            new Dictionary<string, RuntimeCommandHandler>(StringComparer.Ordinal);

        private HttpListener listener;
        private Thread listenerThread;
        private string sessionToken = string.Empty;
        private string sessionPath = string.Empty;
        private volatile bool stopping;
        private bool started;
        private bool unityStartInvoked;
        private bool previousRunInBackground;
        private int activePort;
        private int mainThreadId;

        public bool IsListenerRunning => listener != null && listener.IsListening;
        public int ActivePort => activePort;
        public string SessionPath => sessionPath;

        public string SessionProductName
        {
            get => sessionProductName;
            set => sessionProductName = value;
        }

        public string SessionFileName
        {
            get => sessionFileName;
            set => sessionFileName = value;
        }

        public int PreferredPort
        {
            get => preferredPort;
            set => preferredPort = value;
        }

        private void Awake()
        {
            if (Instance != null && Instance != this)
            {
                Destroy(gameObject);
                return;
            }

            Instance = this;
            mainThreadId = Thread.CurrentThread.ManagedThreadId;
            DontDestroyOnLoad(gameObject);
        }

        private void OnEnable()
        {
            if (unityStartInvoked && Application.isPlaying && runtimeMcpEnabled)
            {
                StartBridge();
            }
        }

        private void Start()
        {
            unityStartInvoked = true;
            if (runtimeMcpEnabled)
            {
                StartBridge();
            }
        }

        private void Update()
        {
            while (warnings.TryDequeue(out string warning))
            {
                Debug.LogWarning($"[GameRuntimeMcpBridge] {warning}", this);
            }

            int budget = Mathf.Max(1, maxRequestsPerFrame);
            while (budget-- > 0 && requests.TryDequeue(out PendingRequest pending))
            {
                if (!pending.TryBegin())
                {
                    continue;
                }

                HttpReply reply;
                try
                {
                    reply = Dispatch(pending.json);
                }
                catch (Exception exception)
                {
                    reply = ErrorReply(200, "dispatch_failed", exception.Message);
                }

                pending.Complete(reply);
            }
        }

        private void OnDisable()
        {
            if (Instance == this)
            {
                StopBridge();
            }
        }

        private void OnDestroy()
        {
            if (Instance == this)
            {
                StopBridge();
                Instance = null;
            }
        }

        private void OnApplicationQuit()
        {
            StopBridge();
        }

        public bool RegisterHandler(
            string command,
            RuntimeCommandHandler handler,
            out string error)
        {
            error = string.Empty;

            if (Thread.CurrentThread.ManagedThreadId != mainThreadId)
            {
                error = "핸들러 등록은 Unity 메인 스레드에서 수행해야 합니다.";
                return false;
            }

            string key = command?.Trim() ?? string.Empty;
            if (string.IsNullOrEmpty(key) || handler == null)
            {
                error = "명령 이름과 핸들러가 필요합니다.";
                return false;
            }

            if (key == RuntimeStatusCommand)
            {
                error = $"{RuntimeStatusCommand}은 브리지 기본 명령입니다.";
                return false;
            }

            if (handlers.TryGetValue(key, out RuntimeCommandHandler existing))
            {
                if (existing == handler)
                {
                    return true;
                }

                error = $"명령 '{key}'은 이미 등록되어 있습니다.";
                return false;
            }

            handlers.Add(key, handler);
            return true;
        }

        public bool UnregisterHandler(
            string command,
            RuntimeCommandHandler handler)
        {
            if (Thread.CurrentThread.ManagedThreadId != mainThreadId)
            {
                return false;
            }

            string key = command?.Trim() ?? string.Empty;
            if (!handlers.TryGetValue(key, out RuntimeCommandHandler existing) ||
                existing != handler)
            {
                return false;
            }

            return handlers.Remove(key);
        }

        public bool StartBridge()
        {
            if (started)
            {
                return IsListenerRunning;
            }

            if (!Application.isPlaying)
            {
                return false;
            }

            previousRunInBackground = Application.runInBackground;
            Application.runInBackground = true;
            sessionToken = Guid.NewGuid().ToString("N");
            stopping = false;
            started = true;

            if (!TryStartListener(out string endpoint, out string failure))
            {
                StopBridge();
                Debug.LogWarning($"[GameRuntimeMcpBridge] {failure}", this);
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
                    $"[GameRuntimeMcpBridge] 세션 파일 기록 실패: {exception.Message}",
                    this);
                return false;
            }

            listenerThread = new Thread(ListenLoop)
            {
                IsBackground = true,
                Name = "GameRuntimeMcpListener"
            };
            listenerThread.Start();

            Debug.Log(
                $"[GameRuntimeMcpBridge] 준비 완료. 세션 파일: {sessionPath}",
                this);
            return true;
        }

        public void StopBridge()
        {
            if (!started)
            {
                return;
            }

            stopping = true;

            try
            {
                listener?.Stop();
            }
            catch
            {
            }

            while (requests.TryDequeue(out PendingRequest pending))
            {
                if (pending.TryAbandon())
                {
                    pending.Complete(
                        ErrorReply(
                            503,
                            "runtime_stopping",
                            "Unity 런타임이 종료 중입니다."));
                }
            }

            if (listenerThread != null && listenerThread.IsAlive)
            {
                listenerThread.Join(500);
            }

            listenerThread = null;

            try
            {
                listener?.Close();
            }
            catch
            {
            }

            listener = null;
            DeleteOwnSessionDescriptor();
            Application.runInBackground = previousRunInBackground;
            sessionToken = string.Empty;
            activePort = 0;
            stopping = false;
            started = false;
        }

        private bool TryStartListener(
            out string endpoint,
            out string failure)
        {
            endpoint = string.Empty;
            failure = string.Empty;
            Exception last = null;

            int first = Mathf.Clamp(preferredPort, 1, 65535);
            int count = Mathf.Max(1, portSearchCount);

            for (int offset = 0; offset < count && first + offset <= 65535; offset++)
            {
                int port = first + offset;
                var candidate = new HttpListener();
                candidate.Prefixes.Add($"http://127.0.0.1:{port}/");

                try
                {
                    candidate.Start();
                    listener = candidate;
                    activePort = port;
                    endpoint = $"http://127.0.0.1:{port}/";
                    return true;
                }
                catch (Exception exception)
                {
                    last = exception;
                    candidate.Close();
                }
            }

            failure =
                $"사용 가능한 로컬 포트를 찾지 못했습니다: {last?.Message}";
            return false;
        }

        private void WriteSessionDescriptor(string endpoint)
        {
            string fileName = Path.GetFileName(sessionFileName);
            if (string.IsNullOrWhiteSpace(fileName))
            {
                fileName = DefaultSessionFile;
            }

            sessionPath = Path.Combine(Application.persistentDataPath, fileName);
            string temp = sessionPath + "." + Guid.NewGuid().ToString("N") + ".tmp";

            var descriptor = new SessionDescriptor
            {
                endpoint = endpoint,
                token = sessionToken,
                rpcPath = NormalizePath(rpcPath),
                product = string.IsNullOrWhiteSpace(sessionProductName)
                    ? Application.productName
                    : sessionProductName.Trim(),
                processId = System.Diagnostics.Process.GetCurrentProcess().Id
            };

            try
            {
                File.WriteAllText(
                    temp,
                    JsonUtility.ToJson(descriptor, true),
                    new UTF8Encoding(false));

                if (File.Exists(sessionPath))
                {
                    File.Delete(sessionPath);
                }

                File.Move(temp, sessionPath);
            }
            finally
            {
                if (File.Exists(temp))
                {
                    File.Delete(temp);
                }
            }
        }

        private void DeleteOwnSessionDescriptor()
        {
            try
            {
                if (!string.IsNullOrEmpty(sessionPath) && File.Exists(sessionPath))
                {
                    SessionDescriptor descriptor =
                        JsonUtility.FromJson<SessionDescriptor>(
                            File.ReadAllText(sessionPath, Encoding.UTF8));

                    if (descriptor != null && descriptor.token == sessionToken)
                    {
                        File.Delete(sessionPath);
                    }
                }
            }
            catch
            {
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
                        warnings.Enqueue("로컬 Listener가 중단되었습니다.");
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
                        warnings.Enqueue($"Listener 오류: {exception.Message}");
                    }
                }
            }
        }

        private void HandleHttp(HttpListenerContext context)
        {
            HttpListenerRequest request = context.Request;
            string path = NormalizePath(rpcPath);

            if (request.RemoteEndPoint != null &&
                !IPAddress.IsLoopback(request.RemoteEndPoint.Address))
            {
                WriteHttp(
                    context.Response,
                    ErrorReply(403, "loopback_only", "로컬 요청만 허용합니다."));
                return;
            }

            if (request.HttpMethod != "POST" ||
                request.Url == null ||
                request.Url.AbsolutePath != path)
            {
                WriteHttp(
                    context.Response,
                    ErrorReply(404, "not_found", $"POST {path}를 사용해야 합니다."));
                return;
            }

            if (request.Headers[TokenHeader] != sessionToken)
            {
                WriteHttp(
                    context.Response,
                    ErrorReply(401, "unauthorized", "세션 토큰이 올바르지 않습니다."));
                return;
            }

            if (!TryReadBody(
                    request,
                    Math.Max(1024, maxRequestBytes),
                    out string json))
            {
                WriteHttp(
                    context.Response,
                    ErrorReply(413, "request_too_large", "요청 본문이 제한을 넘었습니다."));
                return;
            }

            var pending = new PendingRequest { json = json };
            requests.Enqueue(pending);

            if (!pending.completion.Task.Wait(
                    TimeSpan.FromSeconds(Math.Max(1, requestTimeoutSeconds))))
            {
                bool notStarted = pending.TryAbandon();
                WriteHttp(
                    context.Response,
                    ErrorReply(
                        504,
                        notStarted
                            ? "main_thread_timeout_not_started"
                            : "main_thread_timeout_unknown",
                        notStarted
                            ? "메인 스레드가 요청을 시작하지 못했습니다."
                            : "요청 완료 여부를 확인할 수 없습니다."));
                return;
            }

            WriteHttp(context.Response, pending.completion.Task.Result);
        }

        private static bool TryReadBody(
            HttpListenerRequest request,
            int maxBytes,
            out string body)
        {
            body = string.Empty;
            if (request.ContentLength64 > maxBytes)
            {
                return false;
            }

            using (var memory = new MemoryStream())
            {
                byte[] buffer = new byte[4096];
                int total = 0;

                while (true)
                {
                    int read = request.InputStream.Read(buffer, 0, buffer.Length);
                    if (read <= 0)
                    {
                        break;
                    }

                    total += read;
                    if (total > maxBytes)
                    {
                        return false;
                    }

                    memory.Write(buffer, 0, read);
                }

                body = (request.ContentEncoding ?? Encoding.UTF8)
                    .GetString(memory.ToArray());
                return true;
            }
        }

        private HttpReply Dispatch(string requestJson)
        {
            RequestHeader request;

            try
            {
                request = JsonUtility.FromJson<RequestHeader>(requestJson);
            }
            catch (ArgumentException exception)
            {
                return ErrorReply(200, "invalid_json", exception.Message);
            }

            if (request == null || string.IsNullOrWhiteSpace(request.command))
            {
                return ErrorReply(200, "invalid_request", "command가 필요합니다.");
            }

            if (request.protocol != ProtocolVersion)
            {
                return ErrorReply(200, "unsupported_protocol", "지원 프로토콜은 1입니다.");
            }

            if (request.command == RuntimeStatusCommand)
            {
                Scene scene = SceneManager.GetActiveScene();
                return ResultReply(
                    new RuntimeStatusResult
                    {
                        product = string.IsNullOrWhiteSpace(sessionProductName)
                            ? Application.productName
                            : sessionProductName.Trim(),
                        unityVersion = Application.unityVersion,
                        processId = System.Diagnostics.Process.GetCurrentProcess().Id,
                        frameCount = Time.frameCount,
                        sceneName = scene.IsValid() ? scene.name : string.Empty,
                        isPaused = Time.timeScale == 0f
                    });
            }

            if (!handlers.TryGetValue(
                    request.command,
                    out RuntimeCommandHandler handler))
            {
                return ErrorReply(
                    200,
                    "unknown_command",
                    $"등록되지 않은 명령입니다: {request.command}");
            }

            try
            {
                return ResultReply(handler(requestJson));
            }
            catch (Exception exception)
            {
                return ErrorReply(200, "handler_failed", exception.Message);
            }
        }

        private static HttpReply ResultReply(object result)
        {
            string json = result == null ? "null" : JsonUtility.ToJson(result);
            return new HttpReply(200, $"{{\"ok\":true,\"result\":{json}}}");
        }

        private static HttpReply ErrorReply(
            int statusCode,
            string code,
            string message)
        {
            return new HttpReply(
                statusCode,
                "{\"ok\":false,\"error\":{" +
                $"\"code\":\"{Escape(code)}\"," +
                $"\"message\":\"{Escape(message)}\"" +
                "}}");
        }

        private static string NormalizePath(string value)
        {
            string path = string.IsNullOrWhiteSpace(value)
                ? DefaultRpcPath
                : value.Trim();

            return path.StartsWith("/", StringComparison.Ordinal)
                ? path
                : "/" + path;
        }

        private static string Escape(string value)
        {
            if (string.IsNullOrEmpty(value))
            {
                return string.Empty;
            }

            return value
                .Replace("\\", "\\\\")
                .Replace("\"", "\\\"")
                .Replace("\r", "\\r")
                .Replace("\n", "\\n")
                .Replace("\t", "\\t");
        }

        private static void WriteHttp(
            HttpListenerResponse response,
            HttpReply reply)
        {
            byte[] bytes = Encoding.UTF8.GetBytes(reply.body);
            response.StatusCode = reply.statusCode;
            response.ContentType = "application/json; charset=utf-8";
            response.ContentLength64 = bytes.Length;
            response.Headers["Cache-Control"] = "no-store";

            using (Stream output = response.OutputStream)
            {
                output.Write(bytes, 0, bytes.Length);
            }
        }
    }
}
