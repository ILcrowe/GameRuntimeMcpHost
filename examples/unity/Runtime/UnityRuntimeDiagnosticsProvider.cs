using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.Profiling;

namespace GameRuntimeMcp
{
    /// <summary>
    /// 빌드 정보, 증분 로그, 메트릭, 스크린샷 명령을 같은 Bridge에 추가합니다.
    /// 이 컴포넌트를 빼면 진단 명령만 사라집니다.
    /// </summary>
    [DefaultExecutionOrder(-900)]
    [DisallowMultipleComponent]
    [RequireComponent(typeof(GameRuntimeMcpBridge))]
    public sealed class UnityRuntimeDiagnosticsProvider : MonoBehaviour
    {
        public const string BuildInfoCommand = "runtime.build_info";
        public const string LogsReadCommand = "runtime.logs.read";
        public const string MetricsCommand = "runtime.metrics.snapshot";
        public const string ScreenshotCommand = "runtime.capture_screenshot";

        [Serializable]
        private sealed class Request<T>
        {
            public T payload;
        }

        [Serializable]
        private sealed class LogPayload
        {
            public long sinceSequence;
            public string level;
            public string contains;
            public int limit;
            public bool includeStackTrace;
        }

        [Serializable]
        public sealed class BuildInfo
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

        [Serializable]
        public sealed class LogEntry
        {
            public long sequence;
            public string timestampUtc;
            public string level;
            public string message;
            public string stackTrace;
        }

        [Serializable]
        public sealed class LogPage
        {
            public LogEntry[] entries;
            public long oldestSequence;
            public long newestSequence;
            public long nextSequence;
            public bool truncated;
            public bool hasMore;
            public bool cursorReset;
        }

        [Serializable]
        public sealed class Metrics
        {
            public int frameCount;
            public float unscaledDeltaTimeMs;
            public float smoothDeltaTimeMs;
            public float approximateFps;
            public long managedMemoryBytes;
            public long allocatedMemoryBytes;
            public long reservedMemoryBytes;
            public int systemMemoryMb;
            public int graphicsMemoryMb;
        }

        [Serializable]
        public sealed class Screenshot
        {
            public bool queued;
            public string path;
            public int frameCount;
        }

        private sealed class LogRecord
        {
            public long sequence;
            public string timestampUtc;
            public string level;
            public string message;
            public string stackTrace;
        }

        [Header("Log Buffer")]
        [SerializeField, Min(16)] private int logCapacity = 512;
        [SerializeField, Min(128)] private int maxMessageCharacters = 2048;
        [SerializeField, Min(128)] private int maxStackTraceCharacters = 4096;

        [Header("Build / Capture")]
        [SerializeField] private string sourceRevision = "";
        [SerializeField] private string diagnosticsFolderName = "GameRuntimeMcpDiagnostics";

        private readonly object logGate = new object();
        private readonly Queue<LogRecord> logQueue = new Queue<LogRecord>();

        private GameRuntimeMcpBridge bridge;
        private long latestSequence;
        private bool logSubscribed;

        private GameRuntimeMcpBridge.RuntimeCommandHandler buildInfoHandler;
        private GameRuntimeMcpBridge.RuntimeCommandHandler logsHandler;
        private GameRuntimeMcpBridge.RuntimeCommandHandler metricsHandler;
        private GameRuntimeMcpBridge.RuntimeCommandHandler screenshotHandler;

        private void Awake()
        {
            bridge = GetComponent<GameRuntimeMcpBridge>();
            buildInfoHandler = HandleBuildInfo;
            logsHandler = HandleLogs;
            metricsHandler = HandleMetrics;
            screenshotHandler = HandleScreenshot;
        }

        private void OnEnable()
        {
            if (!Application.isPlaying)
                return;

            SubscribeLogs();
            RegisterCommands();
        }

        private void OnDisable()
        {
            UnregisterCommands();
            UnsubscribeLogs();
        }

        public BuildInfo ReadBuildInfo()
        {
            string product = string.IsNullOrWhiteSpace(bridge.SessionProductName)
                ? Application.productName
                : bridge.SessionProductName.Trim();

            return new BuildInfo
            {
                product = product,
                version = Application.version,
                unityVersion = Application.unityVersion,
                buildId = Application.buildGUID,
                developmentBuild = Debug.isDebugBuild,
                platform = Application.platform.ToString(),
                scriptingBackend = GetScriptingBackend(),
                sourceRevision = sourceRevision ?? "",
                processId = System.Diagnostics.Process.GetCurrentProcess().Id
            };
        }

        public LogPage ReadLogs(
            long sinceSequence = 0,
            string level = "",
            string contains = "",
            int limit = 50,
            bool includeStackTrace = false)
        {
            int resultLimit = Mathf.Clamp(limit <= 0 ? 50 : limit, 1, 200);
            long requestedSequence = Math.Max(0L, sinceSequence);
            level = level?.Trim() ?? "";
            contains = contains ?? "";

            lock (logGate)
            {
                bool cursorReset = requestedSequence > latestSequence;
                long cursor = cursorReset ? 0L : requestedSequence;
                long oldest = logQueue.Count > 0 ? logQueue.Peek().sequence : 0L;
                bool truncated = oldest > 0 && cursor < oldest - 1;
                long next = truncated ? oldest - 1 : cursor;
                bool hasMore = false;
                var resultList = new List<LogEntry>(Math.Min(resultLimit, logQueue.Count));

                foreach (LogRecord record in logQueue)
                {
                    if (record.sequence <= cursor)
                        continue;
                    if (resultList.Count >= resultLimit)
                    {
                        hasMore = true;
                        break;
                    }

                    next = record.sequence;
                    if (!string.IsNullOrEmpty(level) &&
                        !string.Equals(record.level, level, StringComparison.OrdinalIgnoreCase))
                        continue;
                    if (!string.IsNullOrEmpty(contains) &&
                        record.message.IndexOf(contains, StringComparison.OrdinalIgnoreCase) < 0)
                        continue;

                    resultList.Add(new LogEntry
                    {
                        sequence = record.sequence,
                        timestampUtc = record.timestampUtc,
                        level = record.level,
                        message = record.message,
                        stackTrace = includeStackTrace ? record.stackTrace : ""
                    });
                }

                return new LogPage
                {
                    entries = resultList.ToArray(),
                    oldestSequence = oldest,
                    newestSequence = latestSequence,
                    nextSequence = next,
                    truncated = truncated,
                    hasMore = hasMore,
                    cursorReset = cursorReset
                };
            }
        }

        public Metrics ReadMetrics()
        {
            float smoothDelta = Time.smoothDeltaTime;
            return new Metrics
            {
                frameCount = Time.frameCount,
                unscaledDeltaTimeMs = Time.unscaledDeltaTime * 1000f,
                smoothDeltaTimeMs = smoothDelta * 1000f,
                approximateFps = smoothDelta > 0f ? 1f / smoothDelta : 0f,
                managedMemoryBytes = GC.GetTotalMemory(false),
                allocatedMemoryBytes = Profiler.GetTotalAllocatedMemoryLong(),
                reservedMemoryBytes = Profiler.GetTotalReservedMemoryLong(),
                systemMemoryMb = SystemInfo.systemMemorySize,
                graphicsMemoryMb = SystemInfo.graphicsMemorySize
            };
        }

        public Screenshot CaptureScreenshot()
        {
            string folderName = Path.GetFileName(diagnosticsFolderName);
            if (string.IsNullOrWhiteSpace(folderName))
                folderName = "GameRuntimeMcpDiagnostics";

            string directory = Path.Combine(Application.persistentDataPath, folderName);
            Directory.CreateDirectory(directory);
            string outputPath = Path.Combine(
                directory,
                $"runtime_{DateTime.UtcNow:yyyyMMdd_HHmmss_fff}.png");
            ScreenCapture.CaptureScreenshot(outputPath);

            return new Screenshot
            {
                queued = true,
                path = outputPath,
                frameCount = Time.frameCount
            };
        }

        private void RegisterCommands()
        {
            if (bridge == null)
                return;

            if (!bridge.RegisterHandler(BuildInfoCommand, buildInfoHandler, out string error) ||
                !bridge.RegisterHandler(LogsReadCommand, logsHandler, out error) ||
                !bridge.RegisterHandler(MetricsCommand, metricsHandler, out error) ||
                !bridge.RegisterHandler(ScreenshotCommand, screenshotHandler, out error))
            {
                UnregisterCommands();
                Debug.LogError($"[Runtime Diagnostics] 명령 등록 실패: {error}", this);
            }
        }

        private void UnregisterCommands()
        {
            if (bridge == null)
                return;

            bridge.UnregisterHandler(BuildInfoCommand, buildInfoHandler);
            bridge.UnregisterHandler(LogsReadCommand, logsHandler);
            bridge.UnregisterHandler(MetricsCommand, metricsHandler);
            bridge.UnregisterHandler(ScreenshotCommand, screenshotHandler);
        }

        private object HandleBuildInfo(string requestJson)
        {
            return ReadBuildInfo();
        }

        private object HandleLogs(string requestJson)
        {
            LogPayload payload = null;
            try
            {
                Request<LogPayload> request = JsonUtility.FromJson<Request<LogPayload>>(requestJson);
                payload = request?.payload;
            }
            catch (ArgumentException)
            {
            }

            payload = payload ?? new LogPayload();
            return ReadLogs(
                payload.sinceSequence,
                payload.level,
                payload.contains,
                payload.limit,
                payload.includeStackTrace);
        }

        private object HandleMetrics(string requestJson)
        {
            return ReadMetrics();
        }

        private object HandleScreenshot(string requestJson)
        {
            return CaptureScreenshot();
        }

        private void SubscribeLogs()
        {
            if (logSubscribed)
                return;
            Application.logMessageReceivedThreaded += OnLogMessageReceived;
            logSubscribed = true;
        }

        private void UnsubscribeLogs()
        {
            if (!logSubscribed)
                return;
            Application.logMessageReceivedThreaded -= OnLogMessageReceived;
            logSubscribed = false;
        }

        private void OnLogMessageReceived(string condition, string stackTrace, LogType type)
        {
            var record = new LogRecord
            {
                timestampUtc = DateTime.UtcNow.ToString("O"),
                level = type.ToString().ToLowerInvariant(),
                message = Bound(condition, Math.Max(128, maxMessageCharacters)),
                stackTrace = Bound(stackTrace, Math.Max(128, maxStackTraceCharacters))
            };

            lock (logGate)
            {
                record.sequence = ++latestSequence;
                logQueue.Enqueue(record);
                int capacity = Mathf.Clamp(logCapacity, 16, 4096);
                while (logQueue.Count > capacity)
                    logQueue.Dequeue();
            }
        }

        private static string Bound(string value, int maxCharacters)
        {
            value = value ?? "";
            return value.Length <= maxCharacters
                ? value
                : value.Substring(0, maxCharacters) + "... (truncated)";
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
    }
}
