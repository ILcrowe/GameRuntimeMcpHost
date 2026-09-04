using System;
using System.Collections;
using System.IO;
using System.Text;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.TestTools;

namespace GameRuntimeMcp.Tests
{
    public sealed class GameRuntimeMcpBridgeTests
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
        private sealed class StateResponse
        {
            public bool ok;
            public SampleGamePlayActionHandler.GameStateResult result;
            public RuntimeError error;
        }

        [Serializable]
        private sealed class SurroundingsResponse
        {
            public bool ok;
            public SampleGamePlayActionHandler.SurroundingsResult result;
            public RuntimeError error;
        }

        [Serializable]
        private sealed class ActionResponse
        {
            public bool ok;
            public SampleGamePlayActionHandler.ActionResult result;
            public RuntimeError error;
        }

        [UnityTest]
        public IEnumerator GameplayToolsRoundTripThroughThePublishedContract()
        {
            bool previousRunInBackground = Application.runInBackground;
            string uniqueSessionName =
                $"game-runtime-mcp-gameplay-test-{Guid.NewGuid():N}.json";

            var runtimeServices = new GameObject("RuntimeServices");
            GameRuntimeMcpBridge bridge =
                runtimeServices.AddComponent<GameRuntimeMcpBridge>();
            bridge.SessionFileName = uniqueSessionName;
            bridge.SessionProductName = "UnityGameRuntimeTest";
            bridge.PreferredPort = 19865;

            var player = new GameObject("ControlledPlayer");
            SampleGamePlayActionHandler handler =
                player.AddComponent<SampleGamePlayActionHandler>();
            handler.ControlledEntity = player.transform;
            handler.MoveSpeed = 30f;

            GameObject target = GameObject.CreatePrimitive(PrimitiveType.Cube);
            target.name = "SampleTerminal";
            target.transform.position = new Vector3(1f, 0f, 1f);
            SampleRuntimeMcpInteractable interactable =
                target.AddComponent<SampleRuntimeMcpInteractable>();

            yield return null;

            Assert.That(bridge.IsListenerRunning, Is.True);
            Assert.That(bridge.ActivePort, Is.GreaterThan(0));
            Assert.That(File.Exists(bridge.SessionPath), Is.True);

            SessionDescriptor descriptor =
                JsonUtility.FromJson<SessionDescriptor>(
                    File.ReadAllText(bridge.SessionPath, Encoding.UTF8));

            Assert.That(descriptor.product, Is.EqualTo("UnityGameRuntimeTest"));

            string unauthorizedJson = null;
            yield return PostRpc(
                descriptor,
                "{\"protocol\":1,\"command\":\"runtime.status\",\"payload\":{}}",
                value => unauthorizedJson = value,
                token: "invalid-token",
                expectedStatusCode: 401);

            StatusResponse unauthorized =
                JsonUtility.FromJson<StatusResponse>(unauthorizedJson);

            Assert.That(unauthorized.ok, Is.False);
            Assert.That(unauthorized.error.code, Is.EqualTo("unauthorized"));

            string statusJson = null;
            yield return PostRpc(
                descriptor,
                "{\"protocol\":1,\"command\":\"runtime.status\",\"payload\":{}}",
                value => statusJson = value);

            StatusResponse status =
                JsonUtility.FromJson<StatusResponse>(statusJson);

            Assert.That(status.ok, Is.True);
            Assert.That(status.result.product, Is.EqualTo("UnityGameRuntimeTest"));
            Assert.That(status.result.processId, Is.GreaterThan(0));

            string stateJson = null;
            yield return PostRpc(
                descriptor,
                "{\"protocol\":1,\"command\":\"game.get_state\",\"payload\":{}}",
                value => stateJson = value);

            StateResponse initialState =
                JsonUtility.FromJson<StateResponse>(stateJson);

            Assert.That(initialState.ok, Is.True);
            Assert.That(initialState.result.entityName, Is.EqualTo(player.name));
            Assert.That(initialState.result.isMoving, Is.False);

            string surroundingsJson = null;
            yield return PostRpc(
                descriptor,
                "{\"protocol\":1,\"command\":\"game.get_surroundings\",\"payload\":{" +
                "\"radius\":5,\"maxResults\":10}}",
                value => surroundingsJson = value);

            SurroundingsResponse surroundings =
                JsonUtility.FromJson<SurroundingsResponse>(surroundingsJson);

            Assert.That(surroundings.ok, Is.True);
            Assert.That(surroundings.result.count, Is.GreaterThan(0));

            SampleGamePlayActionHandler.SurroundingObjectResult targetResult =
                Array.Find(
                    surroundings.result.objects,
                    item => item.name == target.name);

            Assert.That(targetResult, Is.Not.Null);
            Assert.That(targetResult.interactable, Is.True);
            Assert.That(targetResult.targetId, Is.Not.Empty);

            string interactionJson = null;
            string interactionRequest =
                "{\"protocol\":1,\"command\":\"player.interact\",\"payload\":{" +
                $"\"targetId\":\"{targetResult.targetId}\"" +
                "}}";

            yield return PostRpc(
                descriptor,
                interactionRequest,
                value => interactionJson = value);

            ActionResponse interaction =
                JsonUtility.FromJson<ActionResponse>(interactionJson);

            Assert.That(interaction.ok, Is.True);
            Assert.That(interaction.result.accepted, Is.True);
            Assert.That(interactable.InteractionCount, Is.EqualTo(1));

            string moveJson = null;
            yield return PostRpc(
                descriptor,
                "{\"protocol\":1,\"command\":\"player.move_to\",\"payload\":{" +
                "\"targetX\":2,\"targetZ\":0}}",
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

            Assert.That(player.transform.position.x, Is.EqualTo(2f).Within(0.06f));
            Assert.That(player.transform.position.z, Is.EqualTo(0f).Within(0.06f));

            string finalStateJson = null;
            yield return PostRpc(
                descriptor,
                "{\"protocol\":1,\"command\":\"game.get_state\",\"payload\":{}}",
                value => finalStateJson = value);

            StateResponse finalState =
                JsonUtility.FromJson<StateResponse>(finalStateJson);

            Assert.That(finalState.ok, Is.True);
            Assert.That(finalState.result.isMoving, Is.False);
            Assert.That(finalState.result.lastActionStatus, Is.EqualTo("completed"));

            const string ChatMessage = "runtime gameplay sample";
            string chatJson = null;
            yield return PostRpc(
                descriptor,
                "{\"protocol\":1,\"command\":\"chat.send\",\"payload\":{" +
                $"\"message\":\"{ChatMessage}\"" +
                "}}",
                value => chatJson = value);

            ActionResponse chat =
                JsonUtility.FromJson<ActionResponse>(chatJson);

            Assert.That(chat.ok, Is.True);
            Assert.That(chat.result.accepted, Is.True);
            Assert.That(handler.LastChatMessage, Is.EqualTo(ChatMessage));

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

        private static IEnumerator PostRpc(
            SessionDescriptor descriptor,
            string requestJson,
            Action<string> receive,
            string token = null,
            long expectedStatusCode = 200)
        {
            string endpoint =
                descriptor.endpoint.TrimEnd('/') + descriptor.rpcPath;
            byte[] bytes = Encoding.UTF8.GetBytes(requestJson);

            using (var request =
                   new UnityWebRequest(
                       endpoint,
                       UnityWebRequest.kHttpVerbPOST))
            {
                request.uploadHandler = new UploadHandlerRaw(bytes);
                request.downloadHandler = new DownloadHandlerBuffer();
                request.SetRequestHeader("Content-Type", "application/json");
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
