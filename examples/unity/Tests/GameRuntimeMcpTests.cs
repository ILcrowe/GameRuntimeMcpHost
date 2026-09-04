using System;
using System.Collections;
using System.IO;
using System.Text;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.TestTools;

namespace lLCroweTool.GameRuntimeMcpHost.Tests
{
    /// <summary>
    /// 통합 Unity 런타임 샘플의 연결·진단·게임 명령 왕복 테스트입니다.
    /// </summary>
    public sealed class GameRuntimeMcpTests
    {
        [Serializable]
        private sealed class SessionDescriptor
        {
            public string endpoint;
            public string token;
            public string tokenHeader;
            public string rpcPath;
            public string product;
        }

        [Serializable]
        private sealed class RuntimeError
        {
            public string code;
            public string message;
        }

        [Serializable]
        private sealed class StatusResponse
        {
            public bool ok;
            public GameRuntimeMcpBridge.RuntimeStatusResult result;
            public RuntimeError error;
        }

        [Serializable]
        private sealed class BuildInfoResponse
        {
            public bool ok;
            public GameRuntimeMcpBridge.BuildInfoResult result;
            public RuntimeError error;
        }

        [Serializable]
        private sealed class LogsResponse
        {
            public bool ok;
            public GameRuntimeMcpBridge.LogReadResult result;
            public RuntimeError error;
        }

        [Serializable]
        private sealed class MetricsResponse
        {
            public bool ok;
            public GameRuntimeMcpBridge.MetricsSnapshotResult result;
            public RuntimeError error;
        }

        [Serializable]
        private sealed class ScreenshotResponse
        {
            public bool ok;
            public GameRuntimeMcpBridge.ScreenshotResult result;
            public RuntimeError error;
        }

        [Serializable]
        private sealed class StateResponse
        {
            public bool ok;
            public SampleGameRuntimeHandler.GameStateResult result;
            public RuntimeError error;
        }

        [Serializable]
        private sealed class SurroundingsResponse
        {
            public bool ok;
            public SampleGameRuntimeHandler.SurroundingsResult result;
            public RuntimeError error;
        }

        [Serializable]
        private sealed class ActionResponse
        {
            public bool ok;
            public SampleGameRuntimeHandler.ActionResult result;
            public RuntimeError error;
        }

        /// <summary>
        /// 세션 인증부터 게임 행동 검증까지 하나의 공개 계약으로 왕복 확인합니다.
        /// </summary>
        [UnityTest]
        public IEnumerator RuntimeToolsRoundTripThroughOneBridge()
        {
            const string LogMarker =
                "game-runtime-mcp-unified-sample";

            bool previousRunInBackground =
                Application.runInBackground;

            string sessionFileName =
                $"game-runtime-mcp-test-{Guid.NewGuid():N}.json";

            var runtimeServices =
                new GameObject("RuntimeServices");

            GameRuntimeMcpBridge bridge =
                runtimeServices.AddComponent<GameRuntimeMcpBridge>();

            bridge.SessionFileName = sessionFileName;
            bridge.SessionProductName = "UnityGameRuntimeTest";
            bridge.PreferredPort = 19865;
            bridge.EnableDiagnostics = true;

            var player = new GameObject("ControlledPlayer");

            SampleGameRuntimeHandler handler =
                player.AddComponent<SampleGameRuntimeHandler>();

            handler.ControlledEntity = player.transform;
            handler.MoveSpeed = 30f;

            GameObject target =
                GameObject.CreatePrimitive(PrimitiveType.Cube);

            target.name = "SampleTerminal";
            target.transform.position =
                new Vector3(1f, 0f, 1f);

            SampleRuntimeMcpInteractable interactable =
                target.AddComponent<SampleRuntimeMcpInteractable>();

            Physics.SyncTransforms();
            yield return null;

            Assert.That(bridge.IsListenerRunning, Is.True);
            Assert.That(bridge.ActivePort, Is.GreaterThan(0));
            Assert.That(File.Exists(bridge.SessionPath), Is.True);

            SessionDescriptor descriptor =
                JsonUtility.FromJson<SessionDescriptor>(
                    File.ReadAllText(
                        bridge.SessionPath,
                        Encoding.UTF8));

            Assert.That(
                descriptor.product,
                Is.EqualTo("UnityGameRuntimeTest"));

            string unauthorizedJson = null;

            yield return PostRpc(
                descriptor,
                Rpc("runtime.status"),
                value => unauthorizedJson = value,
                token: "invalid-token",
                expectedStatusCode: 401);

            StatusResponse unauthorized =
                JsonUtility.FromJson<StatusResponse>(
                    unauthorizedJson);

            Assert.That(unauthorized.ok, Is.False);
            Assert.That(
                unauthorized.error.code,
                Is.EqualTo("unauthorized"));

            string statusJson = null;

            yield return PostRpc(
                descriptor,
                Rpc("runtime.status"),
                value => statusJson = value);

            StatusResponse status =
                JsonUtility.FromJson<StatusResponse>(
                    statusJson);

            Assert.That(status.ok, Is.True);
            Assert.That(
                status.result.product,
                Is.EqualTo("UnityGameRuntimeTest"));
            Assert.That(
                status.result.processId,
                Is.GreaterThan(0));

            string buildInfoJson = null;

            yield return PostRpc(
                descriptor,
                Rpc("runtime.build_info"),
                value => buildInfoJson = value);

            BuildInfoResponse buildInfo =
                JsonUtility.FromJson<BuildInfoResponse>(
                    buildInfoJson);

            Assert.That(buildInfo.ok, Is.True);
            Assert.That(
                buildInfo.result.product,
                Is.EqualTo("UnityGameRuntimeTest"));
            Assert.That(
                buildInfo.result.unityVersion,
                Is.EqualTo(Application.unityVersion));

            Debug.Log(LogMarker);
            yield return null;

            string logsJson = null;

            yield return PostRpc(
                descriptor,
                Rpc(
                    "runtime.logs.read",
                    "\"sinceSequence\":0," +
                    $"\"contains\":\"{LogMarker}\"," +
                    "\"limit\":10"),
                value => logsJson = value);

            LogsResponse logs =
                JsonUtility.FromJson<LogsResponse>(logsJson);

            Assert.That(logs.ok, Is.True);
            Assert.That(logs.result.entries, Is.Not.Null);
            Assert.That(
                Array.Exists(
                    logs.result.entries,
                    entry =>
                        entry.message.Contains(LogMarker)),
                Is.True);
            Assert.That(
                logs.result.nextSequence,
                Is.GreaterThan(0));

            string metricsJson = null;

            yield return PostRpc(
                descriptor,
                Rpc("runtime.metrics.snapshot"),
                value => metricsJson = value);

            MetricsResponse metrics =
                JsonUtility.FromJson<MetricsResponse>(
                    metricsJson);

            Assert.That(metrics.ok, Is.True);
            Assert.That(
                metrics.result.frameCount,
                Is.GreaterThanOrEqualTo(0));
            Assert.That(
                metrics.result.managedMemoryBytes,
                Is.GreaterThan(0));

            string screenshotJson = null;

            yield return PostRpc(
                descriptor,
                Rpc("runtime.capture_screenshot"),
                value => screenshotJson = value);

            ScreenshotResponse screenshot =
                JsonUtility.FromJson<ScreenshotResponse>(
                    screenshotJson);

            Assert.That(screenshot.ok, Is.True);
            Assert.That(screenshot.result.queued, Is.True);
            Assert.That(
                screenshot.result.path,
                Does.EndWith(".png"));

            string stateJson = null;

            yield return PostRpc(
                descriptor,
                Rpc("game.get_state"),
                value => stateJson = value);

            StateResponse initialState =
                JsonUtility.FromJson<StateResponse>(
                    stateJson);

            Assert.That(initialState.ok, Is.True);
            Assert.That(
                initialState.result.entityName,
                Is.EqualTo(player.name));
            Assert.That(
                initialState.result.isMoving,
                Is.False);

            Physics.SyncTransforms();

            string surroundingsJson = null;

            yield return PostRpc(
                descriptor,
                Rpc(
                    "game.get_surroundings",
                    "\"radius\":5,\"maxResults\":10"),
                value => surroundingsJson = value);

            SurroundingsResponse surroundings =
                JsonUtility.FromJson<SurroundingsResponse>(
                    surroundingsJson);

            Assert.That(surroundings.ok, Is.True);
            Assert.That(
                surroundings.result.count,
                Is.GreaterThan(0));

            SampleGameRuntimeHandler.SurroundingObjectResult
                targetResult =
                    Array.Find(
                        surroundings.result.objects,
                        item => item.name == target.name);

            Assert.That(targetResult, Is.Not.Null);
            Assert.That(targetResult.interactable, Is.True);
            Assert.That(targetResult.targetId, Is.Not.Empty);

            string interactionJson = null;

            yield return PostRpc(
                descriptor,
                Rpc(
                    "player.interact",
                    $"\"targetId\":\"{targetResult.targetId}\""),
                value => interactionJson = value);

            ActionResponse interaction =
                JsonUtility.FromJson<ActionResponse>(
                    interactionJson);

            Assert.That(interaction.ok, Is.True);
            Assert.That(interaction.result.accepted, Is.True);
            Assert.That(
                interactable.InteractionCount,
                Is.EqualTo(1));

            string moveJson = null;

            yield return PostRpc(
                descriptor,
                Rpc(
                    "player.move_to",
                    "\"targetX\":2,\"targetZ\":0"),
                value => moveJson = value);

            ActionResponse move =
                JsonUtility.FromJson<ActionResponse>(moveJson);

            Assert.That(move.ok, Is.True);
            Assert.That(move.result.accepted, Is.True);
            Assert.That(move.result.actionId, Is.Not.Empty);

            int frameBudget = 120;

            while (frameBudget-- > 0 &&
                   Vector3.Distance(
                       player.transform.position,
                       new Vector3(2f, 0f, 0f)) > 0.06f)
            {
                yield return null;
            }

            Assert.That(
                player.transform.position.x,
                Is.EqualTo(2f).Within(0.06f));
            Assert.That(
                player.transform.position.z,
                Is.EqualTo(0f).Within(0.06f));

            string finalStateJson = null;

            yield return PostRpc(
                descriptor,
                Rpc("game.get_state"),
                value => finalStateJson = value);

            StateResponse finalState =
                JsonUtility.FromJson<StateResponse>(
                    finalStateJson);

            Assert.That(finalState.ok, Is.True);
            Assert.That(
                finalState.result.isMoving,
                Is.False);
            Assert.That(
                finalState.result.lastActionStatus,
                Is.EqualTo("completed"));

            const string ChatMessage =
                "runtime gameplay sample";

            string chatJson = null;

            yield return PostRpc(
                descriptor,
                Rpc(
                    "chat.send",
                    $"\"message\":\"{ChatMessage}\""),
                value => chatJson = value);

            ActionResponse chat =
                JsonUtility.FromJson<ActionResponse>(
                    chatJson);

            Assert.That(chat.ok, Is.True);
            Assert.That(chat.result.accepted, Is.True);
            Assert.That(
                handler.LastChatMessage,
                Is.EqualTo(ChatMessage));

            string sessionPath = bridge.SessionPath;

            UnityEngine.Object.Destroy(target);
            UnityEngine.Object.Destroy(player);
            UnityEngine.Object.Destroy(runtimeServices);
            yield return null;

            Assert.That(File.Exists(sessionPath), Is.False);
            Assert.That(
                Application.runInBackground,
                Is.EqualTo(previousRunInBackground));
        }

        private static string Rpc(
            string command,
            string payloadMembers = "")
        {
            return
                "{\"protocol\":1," +
                $"\"command\":\"{command}\"," +
                "\"payload\":{" +
                payloadMembers +
                "}}";
        }

        private static IEnumerator PostRpc(
            SessionDescriptor descriptor,
            string requestJson,
            Action<string> receive,
            string token = null,
            long expectedStatusCode = 200)
        {
            string endpoint =
                descriptor.endpoint.TrimEnd('/') +
                descriptor.rpcPath;

            byte[] bytes =
                Encoding.UTF8.GetBytes(requestJson);

            using (var request =
                   new UnityWebRequest(
                       endpoint,
                       UnityWebRequest.kHttpVerbPOST))
            {
                request.uploadHandler =
                    new UploadHandlerRaw(bytes);

                request.downloadHandler =
                    new DownloadHandlerBuffer();

                request.SetRequestHeader(
                    "Content-Type",
                    "application/json");

                request.SetRequestHeader(
                    descriptor.tokenHeader,
                    token ?? descriptor.token);

                yield return request.SendWebRequest();

                Assert.That(
                    request.responseCode,
                    Is.EqualTo(expectedStatusCode),
                    request.error);

                UnityWebRequest.Result expectedResult =
                    expectedStatusCode < 400
                        ? UnityWebRequest.Result.Success
                        : UnityWebRequest.Result.ProtocolError;

                Assert.That(
                    request.result,
                    Is.EqualTo(expectedResult),
                    request.error);

                receive(request.downloadHandler.text);
            }
        }
    }
}
