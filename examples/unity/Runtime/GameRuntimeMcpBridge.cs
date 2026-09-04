using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Profiling;
using UnityEngine.SceneManagement;

namespace lLCroweTool.GameRuntimeMcpHost
{
    /// <summary>
    /// GameRuntimeMcpHost와 실행 중인 Unity Player를 연결하는 로컬 RPC 브리지입니다.
    /// 세션·인증·메인 스레드 디스패치·명령 등록·범용 진단을 한 컴포넌트에서 관리합니다.
    /// </summary>
    [DefaultExecutionOrder(-1000)]
    [DisallowMultipleComponent]
    public sealed class GameRuntimeMcpBridge : MonoBehaviour
    {
        /// <summary>
        /// 등록된 런타임 명령을 Unity 메인 스레드에서 실행하는 대리자입니다.
        /// </summary>
        public delegate RuntimeCommandResult RuntimeCommandHandler(string requestJson);

        /// <summary>
        /// 런타임 명령의 성공 데이터 또는 실패 정보를 보관합니다.
        /// </summary>
        public sealed class RuntimeCommandResult
        {
            /// <summary>
            /// 명령 성공 여부입니다.
            /// </summary>
            public bool Success;

            /// <summary>
            /// 성공·실패를 식별하는 짧은 코드입니다.
            /// </summary>
            public string Code;

            /// <summary>
            /// 호출자가 확인할 수 있는 설명입니다.
            /// </summary>
            public string Message;

            internal string DataJson;

            /// <summary>
            /// 데이터가 없는 성공 결과를 만듭니다.
            /// </summary>
            public static RuntimeCommandResult Ok()
            {
                return Ok(null);
            }

            /// <summary>
            /// 지정한 데이터를 포함하는 성공 결과를 만듭니다.
            /// </summary>
            public static RuntimeCommandResult Ok(object data)
            {
                return new RuntimeCommandResult
                {
                    Success = true,
                    Code = "OK",
                    Message = string.Empty,
                    DataJson = SerializeJsonValue(data)
                };
            }

            /// <summary>
            /// 지정한 코드와 설명을 포함하는 실패 결과를 만듭니다.
            /// </summary>
            public static RuntimeCommandResult Fail(string code, string message)
            {
                return new RuntimeCommandResult
                {
                    Success = false,
                    Code = string.IsNullOrWhiteSpace(code)
                        ? "COMMAND_FAILED"
                        : code,
                    Message = message ?? string.Empty,
                    DataJson = "null"
                };
            }
        }

        /// <summary>
        /// 명령 이름과 실행 대리자를 한 쌍으로 묶습니다.
        /// </summary>
        public readonly struct CommandBinding
        {
            /// <summary>
            /// Unity 런타임 내부 RPC 명령 이름입니다.
            /// </summary>
            public readonly string Command;

            /// <summary>
            /// 명령 실행 대리자입니다.
            /// </summary>
            public readonly RuntimeCommandHandler Handler;

            /// <summary>
            /// 명령 바인딩을 만듭니다.
            /// </summary>
            public CommandBinding(string command, RuntimeCommandHandler handler)
            {
                Command = command;
                Handler = handler;
            }
        }

        /// <summary>
        /// 연결된 Player의 현재 상태입니다.
        /// </summary>
        [Serializable]
        public sealed class RuntimeStatusResult
        {
            public string product;
            public string unityVersion;
            public int processId;
            public int frameCount;
            public string sceneName;
            public bool isPaused;
            public bool developmentBuild;
        }

        /// <summary>
        /// 현재 실행 중인 빌드를 식별하는 정보입니다.
        /// </summary>
        [Serializable]
        public sealed class BuildInfoResult
        {
            public string product;
            public string version;
            public string unityVersion;
            public string buildId;
            public bool developmentBuild;
            public string platform;
            public string scriptingBackend;
            public string sourceRevision;
            public int processId;
        }

        /// <summary>
        /// 런타임 로그 한 건입니다.
        /// </summary>
        [Serializable]
        public sealed class LogEntryResult
        {
            public long sequence;
            public string timestampUtc;
            public string level;
            public string message;
            public string stackTrace;
        }

        /// <summary>
        /// 제한된 증분 로그 조회 결과입니다.
        /// </summary>
        [Serializable]
        public sealed class LogReadResult
        {
            public LogEntryResult[] entries;
            public long oldestSequence;
            public long newestSequence;
            public long nextSequence;
            public bool truncated;
            public bool hasMore;
            public bool cursorReset;
        }

        /// <summary>
        /// 현재 프레임과 메모리의 단일 성능 스냅샷입니다.
        /// </summary>
        [Serializable]
        public sealed class MetricsSnapshotResult
        {
            public int frameCount;
            public float unscaledDeltaTimeMs;
            public float smoothDeltaTimeMs;
            public float approximateFps;
            public long managedMemoryBytes;
            public long totalAllocatedMemoryBytes;
            public long totalReservedMemoryBytes;
            public long monoHeapBytes;
            public long monoUsedBytes;
            public int systemMemoryMb;
            public int graphicsMemoryMb;
        }

        /// <summary>
        /// 화면 캡처 요청 결과입니다.
        /// </summary>
        [Serializable]
        public sealed class ScreenshotResult
        {
            public bool queued;
            public string path;
            public int frameCount;
        }

        [Serializable]
        private sealed class SessionDescriptor
        {
            public int protocolVersion = ProtocolVersion;
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
        private sealed class DiagnosticsRequest
        {
            public DiagnosticsPayload payload;
        }

        [Serializable]
        private sealed class DiagnosticsPayload
        {
            public long sinceSequence;
            public string level;
            public string contains;
            public int limit;
            public bool includeStackTrace;
        }

        private sealed class RegisteredCommand
        {
            public UnityEngine.Object Owner;
            public RuntimeCommandHandler Handler;
        }

        private sealed class LogRecord
        {
            public long Sequence;
            public string TimestampUtc;
            public string Level;
            public string Message;
            public string StackTrace;
        }

        private sealed class PendingRequest
        {
            public string RequestJson;

            public readonly TaskCompletionSource<HttpReply> Completion =
                new TaskCompletionSource<HttpReply>(
                    TaskCreationOptions.RunContinuationsAsynchronously);

            // 0: 대기, 1: 실행 중, 2: 시작 전 취소, 3: 완료
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
        private const int DefaultPort = 18765;
        private const int MaximumLogCapacity = 4096;
        private const int MaximumLogReadCount = 200;
        private const int DefaultLogReadCount = 50;

        private const string DefaultSessionFileName = "game-runtime-mcp-session.json";
        private const string DefaultRpcPath = "/rpc";
        private const string TokenHeader = "X-Game-Runtime-Token";

        private const string RuntimeStatusCommand = "runtime.status";
        private const string RuntimeBuildInfoCommand = "runtime.build_info";
        private const string RuntimeLogsReadCommand = "runtime.logs.read";
        private const string RuntimeMetricsSnapshotCommand = "runtime.metrics.snapshot";
        private const string RuntimeCaptureScreenshotCommand = "runtime.capture_screenshot";

        /// <summary>
        /// 현재 활성화된 런타임 브리지입니다.
        /// </summary>
        public static GameRuntimeMcpBridge Instance { get; private set; }

        [Header("런타임 MCP")]
        [SerializeField] private bool runtimeMcpEnabled = true;
        [SerializeField] private bool persistAcrossScenes = true;
        [SerializeField] private string sessionProductName = "UnityGameRuntime";
        [SerializeField] private string sessionFileName = DefaultSessionFileName;
        [SerializeField, Min(1)] private int preferredPort = DefaultPort;
        [SerializeField, Min(1)] private int portSearchCount = 10;
        [SerializeField] private string rpcPath = DefaultRpcPath;

        [Header("요청 제한")]
        [SerializeField, Min(1024)] private int maxRequestBytes = 65536;
        [SerializeField, Min(1)] private int requestTimeoutSeconds = 10;
        [SerializeField, Min(1)] private int maxRequestsPerFrame = 8;

        [Header("범용 진단")]
        [SerializeField] private bool enableDiagnostics = true;
        [SerializeField, Min(16)] private int logCapacity = 512;
        [SerializeField, Min(128)] private int maxLogMessageCharacters = 2048;
        [SerializeField, Min(128)] private int maxStackTraceCharacters = 4096;
        [SerializeField] private string diagnosticsFolderName = "GameRuntimeMcpDiagnostics";
        [SerializeField] private string sourceRevision = string.Empty;

        private readonly ConcurrentQueue<PendingRequest> requestQueue =
            new ConcurrentQueue<PendingRequest>();

        private readonly ConcurrentQueue<string> warningQueue =
            new ConcurrentQueue<string>();

        private readonly Dictionary<string, RegisteredCommand> commandMap =
            new Dictionary<string, RegisteredCommand>(StringComparer.Ordinal);

        private readonly object logGate = new object();
        private readonly Queue<LogRecord> logQueue = new Queue<LogRecord>();

        private HttpListener listener;
        private Thread listenerThread;
        private string sessionToken = string.Empty;
        private string sessionPath = string.Empty;
        private volatile bool stopping;
        private bool started;
        private bool unityStartInvoked;
        private bool previousRunInBackground;
        private bool logSubscribed;
        private int activePort;
        private int mainThreadId;
        private long latestLogSequence;

        /// <summary>
        /// 로컬 HTTP Listener가 실행 중인지 여부입니다.
        /// </summary>
        public bool IsListenerRunning =>
            listener != null &&
            listener.IsListening;

        /// <summary>
        /// 현재 선택된 로컬 포트입니다.
        /// </summary>
        public int ActivePort => activePort;

        /// <summary>
        /// 현재 세션 기술자 파일 경로입니다.
        /// </summary>
        public string SessionPath => sessionPath;

        /// <summary>
        /// 세션 자동 탐색에 사용하는 제품 이름입니다.
        /// </summary>
        public string SessionProductName
        {
            get => sessionProductName;
            set => sessionProductName = value;
        }

        /// <summary>
        /// Application.persistentDataPath에 기록할 세션 파일 이름입니다.
        /// </summary>
        public string SessionFileName
        {
            get => sessionFileName;
            set => sessionFileName = value;
        }

        /// <summary>
        /// Listener가 우선 시도할 포트입니다.
        /// </summary>
        public int PreferredPort
        {
            get => preferredPort;
            set => preferredPort = value;
        }

        /// <summary>
        /// 범용 진단 명령 활성화 여부입니다.
        /// </summary>
        public bool EnableDiagnostics
        {
            get => enableDiagnostics;
            set
            {
                enableDiagnostics = value;

                if (!Application.isPlaying || !started)
                {
                    return;
                }

                if (enableDiagnostics)
                {
                    SubscribeLogs();
                }
                else
                {
                    UnsubscribeLogs();
                }
            }
        }

        private void Awake()
        {
            if (Instance != null && Instance != this)
            {
                Destroy(this);
                return;
            }

            Instance = this;
            mainThreadId = Thread.CurrentThread.ManagedThreadId;

            if (persistAcrossScenes)
            {
                DontDestroyOnLoad(gameObject);
            }
        }

        private void OnEnable()
        {
            if (unityStartInvoked &&
                Application.isPlaying &&
                runtimeMcpEnabled)
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
            while (warningQueue.TryDequeue(out string warning))
            {
                Debug.LogWarning($"[GameRuntimeMcpBridge] {warning}", this);
            }

            int requestBudget = Mathf.Max(1, maxRequestsPerFrame);
            while (requestBudget-- > 0 &&
                   requestQueue.TryDequeue(out PendingRequest pending))
            {
                if (!pending.TryBegin())
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
                    reply = ErrorReply(
                        200,
                        "dispatch_failed",
                        exception.Message);
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
            if (Instance != this)
            {
                return;
            }

            StopBridge();
            commandMap.Clear();
            Instance = null;
        }

        private void OnApplicationQuit()
        {
            StopBridge();
        }

        /// <summary>
        /// 명령 이름과 실행 대리자를 바인딩합니다.
        /// </summary>
        public static CommandBinding Bind(
            string command,
            RuntimeCommandHandler handler)
        {
            return new CommandBinding(command, handler);
        }

        /// <summary>
        /// 한 소유자의 명령 묶음을 검증한 뒤 원자적으로 등록합니다.
        /// </summary>
        public bool RegisterAll(
            UnityEngine.Object owner,
            out string error,
            params CommandBinding[] bindingList)
        {
            error = string.Empty;

            if (Thread.CurrentThread.ManagedThreadId != mainThreadId)
            {
                error = "명령 등록은 Unity 메인 스레드에서만 가능합니다.";
                return false;
            }

            if (owner == null)
            {
                error = "명령 소유자가 필요합니다.";
                return false;
            }

            if (bindingList == null || bindingList.Length == 0)
            {
                error = "등록할 명령이 없습니다.";
                return false;
            }

            var normalizedList = new CommandBinding[bindingList.Length];
            var nameSet = new HashSet<string>(StringComparer.Ordinal);

            for (int index = 0; index < bindingList.Length; index++)
            {
                CommandBinding binding = bindingList[index];
                string command = binding.Command?.Trim() ?? string.Empty;

                if (string.IsNullOrEmpty(command))
                {
                    error = $"[{index}] 명령 이름이 비어 있습니다.";
                    return false;
                }

                if (binding.Handler == null)
                {
                    error = $"명령 '{command}'의 실행 대리자가 없습니다.";
                    return false;
                }

                if (IsSystemCommand(command))
                {
                    error = $"명령 '{command}'은 브리지 기본 명령입니다.";
                    return false;
                }

                if (!nameSet.Add(command))
                {
                    error = $"등록 요청 안에 명령 '{command}'이 중복되어 있습니다.";
                    return false;
                }

                if (commandMap.TryGetValue(
                        command,
                        out RegisteredCommand existing) &&
                    (existing.Owner != owner ||
                     existing.Handler != binding.Handler))
                {
                    error = $"명령 '{command}'은 이미 다른 소유자가 등록했습니다.";
                    return false;
                }

                normalizedList[index] =
                    new CommandBinding(command, binding.Handler);
            }

            for (int index = 0; index < normalizedList.Length; index++)
            {
                CommandBinding binding = normalizedList[index];

                if (commandMap.ContainsKey(binding.Command))
                {
                    continue;
                }

                commandMap.Add(
                    binding.Command,
                    new RegisteredCommand
                    {
                        Owner = owner,
                        Handler = binding.Handler
                    });
            }

            return true;
        }

        /// <summary>
        /// 지정한 소유자가 등록한 모든 명령을 제거합니다.
        /// </summary>
        public int UnregisterAll(UnityEngine.Object owner)
        {
            if (Thread.CurrentThread.ManagedThreadId != mainThreadId ||
                owner == null)
            {
                return 0;
            }

            var removeList = new List<string>();

            foreach (KeyValuePair<string, RegisteredCommand> pair in commandMap)
            {
                if (pair.Value.Owner == owner)
                {
                    removeList.Add(pair.Key);
                }
            }

            for (int index = 0; index < removeList.Count; index++)
            {
                commandMap.Remove(removeList[index]);
            }

            return removeList.Count;
        }

        /// <summary>
        /// Listener를 시작하고 새 세션 기술자를 게시합니다.
        /// </summary>
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

            ResetLogBuffer();
            SubscribeLogs();

            if (!TryStartListener(out string endpoint, out string failure))
            {
                StopBridge();
                Debug.LogWarning(
                    $"[GameRuntimeMcpBridge] {failure}",
                    this);
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

        /// <summary>
        /// Listener를 종료하고 현재 세션 기술자를 정리합니다.
        /// </summary>
        public void StopBridge()
        {
            if (!started)
            {
                return;
            }

            stopping = true;
            UnsubscribeLogs();

            try
            {
                listener?.Stop();
            }
            catch (ObjectDisposedException)
            {
            }
            catch (HttpListenerException)
            {
            }

            while (requestQueue.TryDequeue(out PendingRequest pending))
            {
                if (!pending.TryAbandon())
                {
                    continue;
                }

                pending.Complete(
                    ErrorReply(
                        503,
                        "runtime_stopping",
                        "Unity 런타임이 종료 중입니다."));
            }

            if (listenerThread != null &&
                listenerThread.IsAlive)
            {
                listenerThread.Join(500);
            }

            listenerThread = null;

            try
            {
                listener?.Close();
            }
            catch (ObjectDisposedException)
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
            Exception lastException = null;

            int firstPort = Mathf.Clamp(preferredPort, 1, 65535);
            int attemptCount = Mathf.Max(1, portSearchCount);

            for (int offset = 0;
                 offset < attemptCount && firstPort + offset <= 65535;
                 offset++)
            {
                int port = firstPort + offset;
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
                    lastException = exception;
                    candidate.Close();
                }
            }

            failure =
                $"사용 가능한 로컬 포트를 찾지 못했습니다: {lastException?.Message}";
            return false;
        }

        private void WriteSessionDescriptor(string endpoint)
        {
            string safeFileName = Path.GetFileName(sessionFileName);
            if (string.IsNullOrWhiteSpace(safeFileName))
            {
                safeFileName = DefaultSessionFileName;
            }

            sessionPath = Path.Combine(
                Application.persistentDataPath,
                safeFileName);

            string temporaryPath =
                sessionPath + "." + Guid.NewGuid().ToString("N") + ".tmp";

            var descriptor = new SessionDescriptor
            {
                endpoint = endpoint,
                token = sessionToken,
                rpcPath = NormalizePath(rpcPath),
                product = GetSessionProductName(),
                processId = System.Diagnostics.Process
                    .GetCurrentProcess()
                    .Id
            };

            string json = JsonUtility.ToJson(descriptor, true);

            try
            {
                File.WriteAllText(
                    temporaryPath,
                    json,
                    new UTF8Encoding(false));

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

        private void DeleteOwnSessionDescriptor()
        {
            try
            {
                if (string.IsNullOrEmpty(sessionPath) ||
                    !File.Exists(sessionPath))
                {
                    return;
                }

                SessionDescriptor descriptor =
                    JsonUtility.FromJson<SessionDescriptor>(
                        File.ReadAllText(sessionPath, Encoding.UTF8));

                if (descriptor != null &&
                    descriptor.token == sessionToken)
                {
                    File.Delete(sessionPath);
                }
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
            finally
            {
                sessionPath = string.Empty;
            }
        }

        private void ListenLoop()
        {
            while (!stopping &&
                   listener != null &&
                   listener.IsListening)
            {
                try
                {
                    HandleHttp(listener.GetContext());
                }
                catch (HttpListenerException)
                {
                    if (!stopping)
                    {
                        warningQueue.Enqueue(
                            "로컬 Listener가 예기치 않게 중단되었습니다.");
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
                        warningQueue.Enqueue(
                            $"Listener 오류: {exception.Message}");
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
                    ErrorReply(
                        403,
                        "loopback_only",
                        "로컬 요청만 허용합니다."));
                return;
            }

            if (!string.Equals(
                    request.HttpMethod,
                    "POST",
                    StringComparison.OrdinalIgnoreCase) ||
                request.Url == null ||
                !string.Equals(
                    request.Url.AbsolutePath,
                    path,
                    StringComparison.Ordinal))
            {
                WriteHttp(
                    context.Response,
                    ErrorReply(
                        404,
                        "not_found",
                        $"POST {path}를 사용해야 합니다."));
                return;
            }

            if (!string.Equals(
                    request.Headers[TokenHeader],
                    sessionToken,
                    StringComparison.Ordinal))
            {
                WriteHttp(
                    context.Response,
                    ErrorReply(
                        401,
                        "unauthorized",
                        "세션 토큰이 올바르지 않습니다."));
                return;
            }

            int bodyLimit = Math.Max(1024, maxRequestBytes);
            if (!TryReadBody(request, bodyLimit, out string requestJson))
            {
                WriteHttp(
                    context.Response,
                    ErrorReply(
                        413,
                        "request_too_large",
                        $"요청 본문이 {bodyLimit}바이트 제한을 넘었습니다."));
                return;
            }

            var pending = new PendingRequest
            {
                RequestJson = requestJson
            };
            requestQueue.Enqueue(pending);

            TimeSpan timeout = TimeSpan.FromSeconds(
                Math.Max(1, requestTimeoutSeconds));

            if (!pending.Completion.Task.Wait(timeout))
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
                            ? "메인 스레드가 요청 실행을 시작하지 못했습니다."
                            : "요청 실행 여부를 확인할 수 없습니다."));
                return;
            }

            WriteHttp(
                context.Response,
                pending.Completion.Task.Result);
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
                int totalBytes = 0;

                while (true)
                {
                    int readBytes =
                        request.InputStream.Read(
                            buffer,
                            0,
                            buffer.Length);

                    if (readBytes <= 0)
                    {
                        break;
                    }

                    totalBytes += readBytes;
                    if (totalBytes > maxBytes)
                    {
                        return false;
                    }

                    memory.Write(buffer, 0, readBytes);
                }

                Encoding encoding =
                    request.ContentEncoding ?? Encoding.UTF8;

                body = encoding.GetString(memory.ToArray());
                return true;
            }
        }

        private HttpReply Dispatch(string requestJson)
        {
            RequestHeader request;

            try
            {
                request =
                    JsonUtility.FromJson<RequestHeader>(requestJson);
            }
            catch (ArgumentException exception)
            {
                return ErrorReply(
                    200,
                    "invalid_json",
                    exception.Message);
            }

            if (request == null ||
                string.IsNullOrWhiteSpace(request.command))
            {
                return ErrorReply(
                    200,
                    "invalid_request",
                    "command가 필요합니다.");
            }

            if (request.protocol != ProtocolVersion)
            {
                return ErrorReply(
                    200,
                    "unsupported_protocol",
                    $"지원 프로토콜은 {ProtocolVersion}입니다.");
            }

            try
            {
                switch (request.command)
                {
                    case RuntimeStatusCommand:
                        return ResultReply(ReadRuntimeStatus());

                    case RuntimeBuildInfoCommand:
                        return enableDiagnostics
                            ? ResultReply(
                                RuntimeCommandResult.Ok(
                                    ReadBuildInfo()))
                            : DiagnosticsDisabledReply();

                    case RuntimeLogsReadCommand:
                        return enableDiagnostics
                            ? ResultReply(
                                RuntimeCommandResult.Ok(
                                    ReadLogs(requestJson)))
                            : DiagnosticsDisabledReply();

                    case RuntimeMetricsSnapshotCommand:
                        return enableDiagnostics
                            ? ResultReply(
                                RuntimeCommandResult.Ok(
                                    ReadMetricsSnapshot()))
                            : DiagnosticsDisabledReply();

                    case RuntimeCaptureScreenshotCommand:
                        return enableDiagnostics
                            ? ResultReply(
                                RuntimeCommandResult.Ok(
                                    CaptureScreenshot()))
                            : DiagnosticsDisabledReply();
                }

                if (!commandMap.TryGetValue(
                        request.command,
                        out RegisteredCommand registered))
                {
                    return ErrorReply(
                        200,
                        "unknown_command",
                        $"등록되지 않은 명령입니다: {request.command}");
                }

                RuntimeCommandResult result =
                    registered.Handler(requestJson);

                return ResultReply(
                    result ??
                    RuntimeCommandResult.Fail(
                        "null_result",
                        $"명령 '{request.command}'이 결과를 반환하지 않았습니다."));
            }
            catch (Exception exception)
            {
                return ErrorReply(
                    200,
                    "handler_failed",
                    exception.Message);
            }
        }

        private RuntimeCommandResult ReadRuntimeStatus()
        {
            Scene scene = SceneManager.GetActiveScene();

            return RuntimeCommandResult.Ok(
                new RuntimeStatusResult
                {
                    product = GetSessionProductName(),
                    unityVersion = Application.unityVersion,
                    processId = System.Diagnostics.Process
                        .GetCurrentProcess()
                        .Id,
                    frameCount = Time.frameCount,
                    sceneName = scene.IsValid()
                        ? scene.name
                        : string.Empty,
                    isPaused = Time.timeScale == 0f,
                    developmentBuild = Debug.isDebugBuild
                });
        }

        private static HttpReply DiagnosticsDisabledReply()
        {
            return ErrorReply(
                200,
                "diagnostics_disabled",
                "범용 런타임 진단이 비활성화되어 있습니다.");
        }

        private BuildInfoResult ReadBuildInfo()
        {
            return new BuildInfoResult
            {
                product = GetSessionProductName(),
                version = Application.version,
                unityVersion = Application.unityVersion,
                buildId = Application.buildGUID,
                developmentBuild = Debug.isDebugBuild,
                platform = Application.platform.ToString(),
                scriptingBackend = GetScriptingBackend(),
                sourceRevision = sourceRevision ?? string.Empty,
                processId = System.Diagnostics.Process
                    .GetCurrentProcess()
                    .Id
            };
        }

        private LogReadResult ReadLogs(string requestJson)
        {
            DiagnosticsPayload payload = ReadDiagnosticsPayload(requestJson);

            int limit = payload.limit <= 0
                ? DefaultLogReadCount
                : Mathf.Clamp(
                    payload.limit,
                    1,
                    MaximumLogReadCount);

            long requestedSinceSequence =
                Math.Max(0L, payload.sinceSequence);

            string level =
                payload.level?.Trim() ?? string.Empty;

            string contains =
                payload.contains ?? string.Empty;

            lock (logGate)
            {
                bool cursorReset =
                    requestedSinceSequence > latestLogSequence;

                long sinceSequence =
                    cursorReset ? 0L : requestedSinceSequence;

                bool hasRecords = logQueue.Count > 0;

                long oldestSequence = hasRecords
                    ? logQueue.Peek().Sequence
                    : 0L;

                bool truncated =
                    hasRecords &&
                    sinceSequence < oldestSequence - 1;

                long nextSequence = truncated
                    ? oldestSequence - 1
                    : sinceSequence;

                bool hasMore = false;

                var entryList = new List<LogEntryResult>(
                    Math.Min(limit, logQueue.Count));

                foreach (LogRecord record in logQueue)
                {
                    if (record.Sequence <= sinceSequence)
                    {
                        continue;
                    }

                    if (entryList.Count >= limit)
                    {
                        hasMore = true;
                        break;
                    }

                    nextSequence = record.Sequence;

                    if (!string.IsNullOrEmpty(level) &&
                        !string.Equals(
                            record.Level,
                            level,
                            StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }

                    if (!string.IsNullOrEmpty(contains) &&
                        record.Message.IndexOf(
                            contains,
                            StringComparison.OrdinalIgnoreCase) < 0)
                    {
                        continue;
                    }

                    entryList.Add(
                        new LogEntryResult
                        {
                            sequence = record.Sequence,
                            timestampUtc = record.TimestampUtc,
                            level = record.Level,
                            message = record.Message,
                            stackTrace = payload.includeStackTrace
                                ? record.StackTrace
                                : string.Empty
                        });
                }

                return new LogReadResult
                {
                    entries = entryList.ToArray(),
                    oldestSequence = oldestSequence,
                    newestSequence = latestLogSequence,
                    nextSequence = nextSequence,
                    truncated = truncated,
                    hasMore = hasMore,
                    cursorReset = cursorReset
                };
            }
        }

        private MetricsSnapshotResult ReadMetricsSnapshot()
        {
            float smoothDeltaTime = Time.smoothDeltaTime;

            return new MetricsSnapshotResult
            {
                frameCount = Time.frameCount,
                unscaledDeltaTimeMs =
                    Time.unscaledDeltaTime * 1000f,
                smoothDeltaTimeMs =
                    smoothDeltaTime * 1000f,
                approximateFps =
                    smoothDeltaTime > 0f
                        ? 1f / smoothDeltaTime
                        : 0f,
                managedMemoryBytes =
                    GC.GetTotalMemory(false),
                totalAllocatedMemoryBytes =
                    Profiler.GetTotalAllocatedMemoryLong(),
                totalReservedMemoryBytes =
                    Profiler.GetTotalReservedMemoryLong(),
                monoHeapBytes =
                    Profiler.GetMonoHeapSizeLong(),
                monoUsedBytes =
                    Profiler.GetMonoUsedSizeLong(),
                systemMemoryMb =
                    SystemInfo.systemMemorySize,
                graphicsMemoryMb =
                    SystemInfo.graphicsMemorySize
            };
        }

        private ScreenshotResult CaptureScreenshot()
        {
            string safeFolderName =
                Path.GetFileName(diagnosticsFolderName);

            if (string.IsNullOrWhiteSpace(safeFolderName))
            {
                safeFolderName =
                    "GameRuntimeMcpDiagnostics";
            }

            string directory =
                Path.Combine(
                    Application.persistentDataPath,
                    safeFolderName);

            Directory.CreateDirectory(directory);

            string fileName =
                $"runtime_{DateTime.UtcNow:yyyyMMdd_HHmmss_fff}.png";

            string outputPath =
                Path.Combine(directory, fileName);

            ScreenCapture.CaptureScreenshot(outputPath);

            return new ScreenshotResult
            {
                queued = true,
                path = outputPath,
                frameCount = Time.frameCount
            };
        }

        private static DiagnosticsPayload ReadDiagnosticsPayload(
            string requestJson)
        {
            try
            {
                DiagnosticsRequest request =
                    JsonUtility.FromJson<DiagnosticsRequest>(
                        requestJson);

                return request?.payload ??
                       new DiagnosticsPayload();
            }
            catch (ArgumentException)
            {
                return new DiagnosticsPayload();
            }
        }

        private void SubscribeLogs()
        {
            if (!enableDiagnostics || logSubscribed)
            {
                return;
            }

            Application.logMessageReceivedThreaded +=
                OnLogMessageReceived;

            logSubscribed = true;
        }

        private void UnsubscribeLogs()
        {
            if (!logSubscribed)
            {
                return;
            }

            Application.logMessageReceivedThreaded -=
                OnLogMessageReceived;

            logSubscribed = false;
        }

        private void ResetLogBuffer()
        {
            lock (logGate)
            {
                logQueue.Clear();
                latestLogSequence = 0L;
            }
        }

        private void OnLogMessageReceived(
            string condition,
            string stackTrace,
            LogType type)
        {
            int capacity =
                Mathf.Clamp(
                    logCapacity,
                    16,
                    MaximumLogCapacity);

            var record = new LogRecord
            {
                TimestampUtc =
                    DateTime.UtcNow.ToString("O"),
                Level =
                    type.ToString().ToLowerInvariant(),
                Message =
                    Bound(
                        condition,
                        Math.Max(
                            128,
                            maxLogMessageCharacters)),
                StackTrace =
                    Bound(
                        stackTrace,
                        Math.Max(
                            128,
                            maxStackTraceCharacters))
            };

            lock (logGate)
            {
                record.Sequence = ++latestLogSequence;
                logQueue.Enqueue(record);

                while (logQueue.Count > capacity)
                {
                    logQueue.Dequeue();
                }
            }
        }

        private string GetSessionProductName()
        {
            return string.IsNullOrWhiteSpace(sessionProductName)
                ? Application.productName
                : sessionProductName.Trim();
        }

        private static bool IsSystemCommand(string command)
        {
            return command == RuntimeStatusCommand ||
                   command == RuntimeBuildInfoCommand ||
                   command == RuntimeLogsReadCommand ||
                   command == RuntimeMetricsSnapshotCommand ||
                   command == RuntimeCaptureScreenshotCommand;
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

        private static string GetScriptingBackend()
        {
#if ENABLE_IL2CPP
            return "IL2CPP";
#elif ENABLE_MONO
            return "Mono";
#else
            return "Unknown";
#endif
        }

        private static string Bound(
            string value,
            int maximumCharacters)
        {
            value = value ?? string.Empty;

            if (value.Length <= maximumCharacters)
            {
                return value;
            }

            return value.Substring(0, maximumCharacters) +
                   "... (잘림)";
        }

        private static HttpReply ResultReply(
            RuntimeCommandResult result)
        {
            if (result == null)
            {
                return ErrorReply(
                    200,
                    "null_result",
                    "명령 결과가 없습니다.");
            }

            if (!result.Success)
            {
                return ErrorReply(
                    200,
                    result.Code,
                    result.Message);
            }

            string dataJson =
                string.IsNullOrWhiteSpace(result.DataJson)
                    ? "null"
                    : result.DataJson;

            return new HttpReply(
                200,
                $"{{\"ok\":true,\"result\":{dataJson}}}");
        }

        private static HttpReply ErrorReply(
            int statusCode,
            string code,
            string message)
        {
            return new HttpReply(
                statusCode,
                "{\"ok\":false,\"error\":{" +
                $"\"code\":\"{EscapeJsonString(code)}\"," +
                $"\"message\":\"{EscapeJsonString(message)}\"" +
                "}}");
        }

        private static string SerializeJsonValue(object value)
        {
            if (value == null)
            {
                return "null";
            }

            if (value is string text)
            {
                return $"\"{EscapeJsonString(text)}\"";
            }

            if (value is bool boolean)
            {
                return boolean ? "true" : "false";
            }

            if (value is char character)
            {
                return $"\"{EscapeJsonString(character.ToString())}\"";
            }

            Type type = value.GetType();
            if (type.IsEnum)
            {
                return $"\"{EscapeJsonString(value.ToString())}\"";
            }

            if (type.IsPrimitive || value is decimal)
            {
                return Convert.ToString(
                           value,
                           CultureInfo.InvariantCulture) ??
                       "null";
            }

            return JsonUtility.ToJson(value);
        }

        private static string EscapeJsonString(string value)
        {
            if (string.IsNullOrEmpty(value))
            {
                return string.Empty;
            }

            var builder =
                new StringBuilder(value.Length + 8);

            foreach (char character in value)
            {
                switch (character)
                {
                    case '"':
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
                            builder.Append(
                                ((int)character)
                                .ToString("x4"));
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

        private static void WriteHttp(
            HttpListenerResponse response,
            HttpReply reply)
        {
            byte[] bytes =
                Encoding.UTF8.GetBytes(reply.Body);

            response.StatusCode = reply.StatusCode;
            response.ContentType =
                "application/json; charset=utf-8";
            response.ContentLength64 = bytes.Length;
            response.Headers["Cache-Control"] = "no-store";

            using (Stream output = response.OutputStream)
            {
                output.Write(bytes, 0, bytes.Length);
            }
        }
    }
}
