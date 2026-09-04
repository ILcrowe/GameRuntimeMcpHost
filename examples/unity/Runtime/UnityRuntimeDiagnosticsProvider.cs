using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.Profiling;

namespace lLCroweTool.GameRuntimeMcpHost
{
    /// <summary>
    /// Optional, game-independent diagnostics for a running Unity Player.
    ///
    /// This component does not own transport or gameplay authority. A game-owned
    /// runtime adapter may map the public methods to its MCP/RPC command surface.
    /// Attach it explicitly to a runtime services object when these diagnostics
    /// are wanted.
    /// </summary>
    public sealed class UnityRuntimeDiagnosticsProvider : MonoBehaviour
    {
        [Serializable]
        public sealed class BuildInfoResult
        {
            public string product;
            public string version;
            public string engineVersion;
            public string buildId;
            public bool developmentBuild;
            public string platform;
            public string scriptingBackend;
            public string sourceRevision;
            public int processId;
        }

        [Serializable]
        public sealed class LogReadRequest
        {
            public long sinceSequence;
            public string level;
            public string contains;
            public int limit = 50;
            public bool includeStackTrace;
        }

        [Serializable]
        public sealed class LogEntryResult
        {
            public long sequence;
            public string timestampUtc;
            public string level;
            public string message;
            public string stackTrace;
        }

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

        [Serializable]
        public sealed class ScreenshotResult
        {
            public bool queued;
            public string path;
            public int frameCount;
        }

        private sealed class LogRecord
        {
            public long Sequence;
            public string TimestampUtc;
            public string Level;
            public string Message;
            public string StackTrace;
        }

        private const int MaximumLogCapacity = 4096;
        private const int MaximumLogReadCount = 200;
        private const int DefaultLogReadCount = 50;

        [Header("Runtime diagnostics")]
        [SerializeField, Min(16)] private int logCapacity = 512;
        [SerializeField, Min(128)] private int maxLogMessageCharacters = 2048;
        [SerializeField, Min(128)] private int maxStackTraceCharacters = 4096;
        [SerializeField] private string diagnosticsFolderName = "GameRuntimeMcpDiagnostics";
        [SerializeField] private string sourceRevision = string.Empty;

        private readonly object logGate = new object();
        private readonly Queue<LogRecord> logRecords = new Queue<LogRecord>();
        private long latestLogSequence;
        private bool logSubscribed;

        private void OnEnable()
        {
            SubscribeLogs();
        }

        private void OnDisable()
        {
            UnsubscribeLogs();
        }

        /// <summary>Reads stable identity for the currently running Player build.</summary>
        public BuildInfoResult ReadBuildInfo()
        {
            return new BuildInfoResult
            {
                product = Application.productName,
                version = Application.version,
                engineVersion = Application.unityVersion,
                buildId = Application.buildGUID,
                developmentBuild = Debug.isDebugBuild,
                platform = Application.platform.ToString(),
                scriptingBackend = GetScriptingBackend(),
                sourceRevision = sourceRevision ?? string.Empty,
                processId = System.Diagnostics.Process.GetCurrentProcess().Id
            };
        }

        /// <summary>Reads a bounded incremental slice of captured Unity logs.</summary>
        public LogReadResult ReadLogs(LogReadRequest request = null)
        {
            request ??= new LogReadRequest();
            int limit = request.limit <= 0
                ? DefaultLogReadCount
                : Mathf.Clamp(request.limit, 1, MaximumLogReadCount);
            long requestedSinceSequence = Math.Max(0L, request.sinceSequence);
            string level = request.level?.Trim() ?? string.Empty;
            string contains = request.contains ?? string.Empty;

            lock (logGate)
            {
                bool cursorReset = requestedSinceSequence > latestLogSequence;
                long sinceSequence = cursorReset ? 0L : requestedSinceSequence;
                bool hasRecords = logRecords.Count > 0;
                long oldestSequence = hasRecords
                    ? logRecords.Peek().Sequence
                    : 0L;
                bool truncated = hasRecords && sinceSequence < oldestSequence - 1;
                long nextSequence = truncated
                    ? oldestSequence - 1
                    : sinceSequence;
                bool hasMore = false;
                var resultList = new List<LogEntryResult>(Math.Min(limit, logRecords.Count));

                foreach (LogRecord record in logRecords)
                {
                    if (record.Sequence <= sinceSequence)
                    {
                        continue;
                    }

                    if (resultList.Count >= limit)
                    {
                        hasMore = true;
                        break;
                    }

                    // Advance across inspected non-matching records, but never skip records
                    // beyond the bounded result page.
                    nextSequence = record.Sequence;

                    if (!string.IsNullOrEmpty(level) &&
                        !string.Equals(record.Level, level, StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }

                    if (!string.IsNullOrEmpty(contains) &&
                        record.Message.IndexOf(contains, StringComparison.OrdinalIgnoreCase) < 0)
                    {
                        continue;
                    }

                    resultList.Add(new LogEntryResult
                    {
                        sequence = record.Sequence,
                        timestampUtc = record.TimestampUtc,
                        level = record.Level,
                        message = record.Message,
                        stackTrace = request.includeStackTrace
                            ? record.StackTrace
                            : string.Empty
                    });
                }

                return new LogReadResult
                {
                    entries = resultList.ToArray(),
                    oldestSequence = oldestSequence,
                    newestSequence = latestLogSequence,
                    nextSequence = nextSequence,
                    truncated = truncated,
                    hasMore = hasMore,
                    cursorReset = cursorReset
                };
            }
        }

        /// <summary>Reads one cheap, bounded performance snapshot from the current frame.</summary>
        public MetricsSnapshotResult ReadMetricsSnapshot()
        {
            float smoothDeltaTime = Time.smoothDeltaTime;
            return new MetricsSnapshotResult
            {
                frameCount = Time.frameCount,
                unscaledDeltaTimeMs = Time.unscaledDeltaTime * 1000f,
                smoothDeltaTimeMs = smoothDeltaTime * 1000f,
                approximateFps = smoothDeltaTime > 0f ? 1f / smoothDeltaTime : 0f,
                managedMemoryBytes = GC.GetTotalMemory(false),
                totalAllocatedMemoryBytes = Profiler.GetTotalAllocatedMemoryLong(),
                totalReservedMemoryBytes = Profiler.GetTotalReservedMemoryLong(),
                monoHeapBytes = Profiler.GetMonoHeapSizeLong(),
                monoUsedBytes = Profiler.GetMonoUsedSizeLong(),
                systemMemoryMb = SystemInfo.systemMemorySize,
                graphicsMemoryMb = SystemInfo.graphicsMemorySize
            };
        }

        /// <summary>
        /// Queues one screenshot under Application.persistentDataPath.
        /// The caller does not supply a filesystem path.
        /// </summary>
        public ScreenshotResult CaptureScreenshot()
        {
            string safeFolder = Path.GetFileName(diagnosticsFolderName);
            if (string.IsNullOrWhiteSpace(safeFolder))
            {
                safeFolder = "GameRuntimeMcpDiagnostics";
            }

            string directory = Path.Combine(Application.persistentDataPath, safeFolder);
            Directory.CreateDirectory(directory);
            string fileName = $"runtime_{DateTime.UtcNow:yyyyMMdd_HHmmss_fff}.png";
            string outputPath = Path.Combine(directory, fileName);
            ScreenCapture.CaptureScreenshot(outputPath);

            return new ScreenshotResult
            {
                queued = true,
                path = outputPath,
                frameCount = Time.frameCount
            };
        }

        private void SubscribeLogs()
        {
            if (logSubscribed)
            {
                return;
            }

            Application.logMessageReceivedThreaded += OnLogMessageReceived;
            logSubscribed = true;
        }

        private void UnsubscribeLogs()
        {
            if (!logSubscribed)
            {
                return;
            }

            Application.logMessageReceivedThreaded -= OnLogMessageReceived;
            logSubscribed = false;
        }

        private void OnLogMessageReceived(string condition, string stackTrace, LogType type)
        {
            int capacity = Mathf.Clamp(logCapacity, 16, MaximumLogCapacity);
            var record = new LogRecord
            {
                TimestampUtc = DateTime.UtcNow.ToString("O"),
                Level = type.ToString().ToLowerInvariant(),
                Message = Bound(condition, Math.Max(128, maxLogMessageCharacters)),
                StackTrace = Bound(stackTrace, Math.Max(128, maxStackTraceCharacters))
            };

            lock (logGate)
            {
                record.Sequence = ++latestLogSequence;
                logRecords.Enqueue(record);
                while (logRecords.Count > capacity)
                {
                    logRecords.Dequeue();
                }
            }
        }

        private static string Bound(string value, int maximumCharacters)
        {
            value ??= string.Empty;
            if (value.Length <= maximumCharacters)
            {
                return value;
            }

            return value.Substring(0, maximumCharacters) + "... (truncated)";
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
