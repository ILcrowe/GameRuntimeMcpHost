using System.Collections;
using System.IO;
using System.Text;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.TestTools;

namespace lLCroweTool.GameRuntimeMcpHost.Tests
{
    public sealed class UnityRuntimeMcpSampleBridgeTests
    {
        [System.Serializable]
        private sealed class SessionDescriptor
        {
            public string endpoint;
            public string token;
            public string tokenHeader;
            public string rpcPath;
            public string product;
        }

        [System.Serializable]
        private sealed class RuntimeRpcResponse
        {
            public bool ok;
            public SampleResult result;
            public RuntimeRpcError error;
        }

        [System.Serializable]
        private sealed class BuildInfoRpcResponse
        {
            public bool ok;
            public UnityRuntimeDiagnosticsProvider.BuildInfoResult result;
            public RuntimeRpcError error;
        }

        [System.Serializable]
        private sealed class LogsRpcResponse
        {
            public bool ok;
            public UnityRuntimeDiagnosticsProvider.LogReadResult result;
            public RuntimeRpcError error;
        }

        [System.Serializable]
        private sealed class MetricsRpcResponse
        {
            public bool ok;
            public UnityRuntimeDiagnosticsProvider.MetricsSnapshotResult result;
            public RuntimeRpcError error;
        }

        [System.Serializable]
        private sealed class SampleResult
        {
            public string product;
            public string unityVersion;
            public string message;
        }

        [System.Serializable]
        private sealed class RuntimeRpcError
        {
            public string code;
            public string message;
        }

        [UnityTest]
        public IEnumerator RuntimeAndDiagnosticsRoundTripUseThePublishedContract()
        {
            const string LogMarker = "runtime-diagnostics-round-trip";
            bool previousRunInBackground = Application.runInBackground;
            var hostObject = new GameObject("RuntimeServices");
            hostObject.AddComponent<UnityRuntimeDiagnosticsProvider>();
            UnityRuntimeMcpSampleBridge bridge =
                hostObject.AddComponent<UnityRuntimeMcpSampleBridge>();

            yield return null;

            Assert.That(bridge.IsListenerRunning, Is.True);
            Assert.That(bridge.ActivePort, Is.GreaterThan(0));
            Assert.That(File.Exists(bridge.SessionPath), Is.True);

            SessionDescriptor descriptor = JsonUtility.FromJson<SessionDescriptor>(
                File.ReadAllText(bridge.SessionPath, Encoding.UTF8));
            Assert.That(descriptor.product, Is.EqualTo(Application.productName));

            string unauthorizedJson = null;
            yield return PostRpc(
                descriptor,
                "{\"protocol\":1,\"command\":\"runtime.status\",\"payload\":{}}",
                value => unauthorizedJson = value,
                "invalid-token",
                401);
            RuntimeRpcResponse unauthorized =
                JsonUtility.FromJson<RuntimeRpcResponse>(unauthorizedJson);
            Assert.That(unauthorized.ok, Is.False);
            Assert.That(unauthorized.error.code, Is.EqualTo("unauthorized"));

            string statusJson = null;
            yield return PostRpc(
                descriptor,
                "{\"protocol\":1,\"command\":\"runtime.status\",\"payload\":{}}",
                value => statusJson = value);
            RuntimeRpcResponse status = JsonUtility.FromJson<RuntimeRpcResponse>(statusJson);
            Assert.That(status.ok, Is.True);
            Assert.That(status.result.product, Is.EqualTo(Application.productName));
            Assert.That(status.result.unityVersion, Is.EqualTo(Application.unityVersion));

            string buildInfoJson = null;
            yield return PostRpc(
                descriptor,
                "{\"protocol\":1,\"command\":\"runtime.build_info\",\"payload\":{}}",
                value => buildInfoJson = value);
            BuildInfoRpcResponse buildInfo =
                JsonUtility.FromJson<BuildInfoRpcResponse>(buildInfoJson);
            Assert.That(buildInfo.ok, Is.True);
            Assert.That(buildInfo.result.product, Is.EqualTo(Application.productName));
            Assert.That(buildInfo.result.engineVersion, Is.EqualTo(Application.unityVersion));
            Assert.That(buildInfo.result.processId, Is.GreaterThan(0));

            Debug.Log(LogMarker);
            yield return null;

            string logsJson = null;
            yield return PostRpc(
                descriptor,
                "{\"protocol\":1,\"command\":\"runtime.logs.read\",\"payload\":{" +
                "\"sinceSequence\":0,\"contains\":\"runtime-diagnostics-round-trip\"," +
                "\"limit\":10}}",
                value => logsJson = value);
            LogsRpcResponse logs = JsonUtility.FromJson<LogsRpcResponse>(logsJson);
            Assert.That(logs.ok, Is.True);
            Assert.That(logs.result.entries, Is.Not.Null);
            Assert.That(
                System.Array.Exists(
                    logs.result.entries,
                    entry => entry.message.Contains(LogMarker)),
                Is.True);
            Assert.That(logs.result.nextSequence, Is.GreaterThan(0));
            Assert.That(logs.result.newestSequence, Is.GreaterThanOrEqualTo(logs.result.nextSequence));

            string metricsJson = null;
            yield return PostRpc(
                descriptor,
                "{\"protocol\":1,\"command\":\"runtime.metrics.snapshot\",\"payload\":{}}",
                value => metricsJson = value);
            MetricsRpcResponse metrics =
                JsonUtility.FromJson<MetricsRpcResponse>(metricsJson);
            Assert.That(metrics.ok, Is.True);
            Assert.That(metrics.result.frameCount, Is.GreaterThanOrEqualTo(0));
            Assert.That(metrics.result.managedMemoryBytes, Is.GreaterThan(0));

            string echoJson = null;
            yield return PostRpc(
                descriptor,
                "{\"protocol\":1,\"command\":\"sample.echo\",\"payload\":{\"message\":\"hello runtime\"}}",
                value => echoJson = value);
            RuntimeRpcResponse echo = JsonUtility.FromJson<RuntimeRpcResponse>(echoJson);
            Assert.That(echo.ok, Is.True);
            Assert.That(echo.result.message, Is.EqualTo("hello runtime"));

            string sessionPath = bridge.SessionPath;
            UnityEngine.Object.Destroy(hostObject);
            yield return null;

            Assert.That(File.Exists(sessionPath), Is.False);
            Assert.That(Application.runInBackground, Is.EqualTo(previousRunInBackground));
        }

        private static IEnumerator PostRpc(
            SessionDescriptor descriptor,
            string requestJson,
            System.Action<string> receive,
            string token = null,
            long expectedStatusCode = 200)
        {
            string endpoint = descriptor.endpoint.TrimEnd('/') + descriptor.rpcPath;
            byte[] bytes = Encoding.UTF8.GetBytes(requestJson);
            using var request = new UnityWebRequest(endpoint, UnityWebRequest.kHttpVerbPOST)
            {
                uploadHandler = new UploadHandlerRaw(bytes),
                downloadHandler = new DownloadHandlerBuffer()
            };
            request.SetRequestHeader("Content-Type", "application/json");
            request.SetRequestHeader(descriptor.tokenHeader, token ?? descriptor.token);

            yield return request.SendWebRequest();

            Assert.That(request.responseCode, Is.EqualTo(expectedStatusCode), request.error);
            UnityWebRequest.Result expectedResult = expectedStatusCode < 400
                ? UnityWebRequest.Result.Success
                : UnityWebRequest.Result.ProtocolError;
            Assert.That(request.result, Is.EqualTo(expectedResult), request.error);
            receive(request.downloadHandler.text);
        }
    }
}
