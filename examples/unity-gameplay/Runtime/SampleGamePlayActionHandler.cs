using System;
using System.Collections.Generic;
using System.Globalization;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.SceneManagement;

namespace GameRuntimeMcp
{
    /// <summary>
    /// LLM이 게임 상태를 관찰하고 제한된 플레이 명령을 호출하는 샘플입니다.
    /// 실제 프로젝트에서는 상태·이동·상호작용·채팅을 게임의 권위 서비스에 연결합니다.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class SampleGamePlayActionHandler : MonoBehaviour
    {
        public const string GetGameStateCommand = "game.get_state";
        public const string GetSurroundingsCommand = "game.get_surroundings";
        public const string PlayerMoveToCommand = "player.move_to";
        public const string PlayerInteractCommand = "player.interact";
        public const string SendInGameChatCommand = "chat.send";

        [Serializable]
        public sealed class ChatMessageEvent : UnityEvent<string>
        {
        }

        [Serializable]
        private sealed class RequestEnvelope
        {
            public Payload payload;
        }

        [Serializable]
        private sealed class Payload
        {
            public float radius;
            public int maxResults;
            public float targetX;
            public float targetZ;
            public string targetId;
            public string targetName;
            public string message;
        }

        [Serializable]
        public sealed class GameStateResult
        {
            public string entityName;
            public float positionX;
            public float positionY;
            public float positionZ;
            public int health;
            public int maxHealth;
            public string currentObjective;
            public float gameTime;
            public string sceneName;
            public bool isMoving;
            public float moveTargetX;
            public float moveTargetZ;
            public float remainingDistance;
            public string activeActionId;
            public string lastActionStatus;
            public string lastChatMessage;
        }

        [Serializable]
        public sealed class SurroundingObjectResult
        {
            public string targetId;
            public string name;
            public string tag;
            public float distance;
            public float worldX;
            public float worldY;
            public float worldZ;
            public bool interactable;
        }

        [Serializable]
        public sealed class SurroundingsResult
        {
            public float radius;
            public int count;
            public SurroundingObjectResult[] objects;
        }

        [Serializable]
        public sealed class ActionResult
        {
            public bool accepted;
            public string code;
            public string message;
            public string actionId;
            public string status;
            public string targetId;
            public string targetName;
            public float targetX;
            public float targetZ;
        }

        [Header("Controlled Entity")]
        [SerializeField] private Transform controlledEntity;
        [SerializeField, Min(0.01f)] private float moveSpeed = 5f;
        [SerializeField, Min(0f)] private float stoppingDistance = 0.05f;
        [SerializeField, Min(0.1f)] private float maxMoveDistance = 100f;

        [Header("Observation")]
        [SerializeField, Min(0.1f)] private float defaultScanRadius = 15f;
        [SerializeField, Min(0.1f)] private float maxScanRadius = 50f;
        [SerializeField, Range(1, 50)] private int defaultMaxResults = 10;
        [SerializeField] private LayerMask surroundingsMask = ~0;

        [Header("Interaction")]
        [SerializeField, Min(0.1f)] private float interactionRadius = 5f;

        [Header("Sample State")]
        [SerializeField, Min(0)] private int health = 100;
        [SerializeField, Min(1)] private int maxHealth = 100;
        [SerializeField] private string currentObjective =
            "현재 지역을 탐색하고 목표를 확인합니다.";
        [SerializeField] private ChatMessageEvent onChatMessage =
            new ChatMessageEvent();

        private GameRuntimeMcpBridge bridge;
        private bool registered;
        private float nextRegistrationRetryTime;

        private GameRuntimeMcpBridge.RuntimeCommandHandler stateHandler;
        private GameRuntimeMcpBridge.RuntimeCommandHandler surroundingsHandler;
        private GameRuntimeMcpBridge.RuntimeCommandHandler moveHandler;
        private GameRuntimeMcpBridge.RuntimeCommandHandler interactHandler;
        private GameRuntimeMcpBridge.RuntimeCommandHandler chatHandler;

        private bool hasMoveTarget;
        private Vector3 moveTarget;
        private string activeActionId = string.Empty;
        private string lastActionStatus = "idle";
        private string lastChatMessage = string.Empty;

        public Transform ControlledEntity
        {
            get => controlledEntity;
            set => controlledEntity = value;
        }

        public float MoveSpeed
        {
            get => moveSpeed;
            set => moveSpeed = Mathf.Max(0.01f, value);
        }

        public string LastChatMessage => lastChatMessage;

        private void Awake()
        {
            stateHandler = HandleGetGameState;
            surroundingsHandler = HandleGetSurroundings;
            moveHandler = HandlePlayerMoveTo;
            interactHandler = HandlePlayerInteract;
            chatHandler = HandleSendInGameChat;

            if (controlledEntity == null)
            {
                controlledEntity = transform;
            }
        }

        private void OnEnable()
        {
            nextRegistrationRetryTime = 0f;
            TryRegister();
        }

        private void Update()
        {
            if (!registered && Time.unscaledTime >= nextRegistrationRetryTime)
            {
                TryRegister();
            }

            UpdateMovement();
        }

        private void OnDisable()
        {
            Unregister();
        }

        private void TryRegister()
        {
            if (registered)
            {
                return;
            }

            bridge = GameRuntimeMcpBridge.Instance;
            if (bridge == null)
            {
                nextRegistrationRetryTime = Time.unscaledTime + 0.5f;
                return;
            }

            var added = new List<KeyValuePair<string, GameRuntimeMcpBridge.RuntimeCommandHandler>>();

            if (!Add(GetGameStateCommand, stateHandler, added, out string error) ||
                !Add(GetSurroundingsCommand, surroundingsHandler, added, out error) ||
                !Add(PlayerMoveToCommand, moveHandler, added, out error) ||
                !Add(PlayerInteractCommand, interactHandler, added, out error) ||
                !Add(SendInGameChatCommand, chatHandler, added, out error))
            {
                foreach (KeyValuePair<string, GameRuntimeMcpBridge.RuntimeCommandHandler> item in added)
                {
                    bridge.UnregisterHandler(item.Key, item.Value);
                }

                nextRegistrationRetryTime = Time.unscaledTime + 2f;
                Debug.LogWarning($"[Runtime MCP Sample] 핸들러 등록 실패: {error}", this);
                bridge = null;
                return;
            }

            registered = true;
        }

        private bool Add(
            string command,
            GameRuntimeMcpBridge.RuntimeCommandHandler handler,
            ICollection<KeyValuePair<string, GameRuntimeMcpBridge.RuntimeCommandHandler>> added,
            out string error)
        {
            if (!bridge.RegisterHandler(command, handler, out error))
            {
                return false;
            }

            added.Add(
                new KeyValuePair<string, GameRuntimeMcpBridge.RuntimeCommandHandler>(
                    command,
                    handler));
            return true;
        }

        private void Unregister()
        {
            if (!registered || bridge == null)
            {
                registered = false;
                bridge = null;
                return;
            }

            bridge.UnregisterHandler(GetGameStateCommand, stateHandler);
            bridge.UnregisterHandler(GetSurroundingsCommand, surroundingsHandler);
            bridge.UnregisterHandler(PlayerMoveToCommand, moveHandler);
            bridge.UnregisterHandler(PlayerInteractCommand, interactHandler);
            bridge.UnregisterHandler(SendInGameChatCommand, chatHandler);

            registered = false;
            bridge = null;
        }

        private void UpdateMovement()
        {
            if (!hasMoveTarget || controlledEntity == null)
            {
                return;
            }

            Vector3 current = controlledEntity.position;
            Vector3 target = new Vector3(moveTarget.x, current.y, moveTarget.z);
            float stop = Mathf.Max(0f, stoppingDistance);

            if (Vector3.Distance(current, target) <= stop)
            {
                controlledEntity.position = target;
                hasMoveTarget = false;
                lastActionStatus = "completed";
                return;
            }

            controlledEntity.position = Vector3.MoveTowards(
                current,
                target,
                Mathf.Max(0.01f, moveSpeed) * Time.deltaTime);
        }

        private object HandleGetGameState(string requestJson)
        {
            Vector3 position = controlledEntity != null
                ? controlledEntity.position
                : Vector3.zero;
            Vector3 target = new Vector3(moveTarget.x, position.y, moveTarget.z);

            return new GameStateResult
            {
                entityName = controlledEntity != null
                    ? controlledEntity.name
                    : "Unknown",
                positionX = position.x,
                positionY = position.y,
                positionZ = position.z,
                health = Mathf.Clamp(health, 0, Mathf.Max(1, maxHealth)),
                maxHealth = Mathf.Max(1, maxHealth),
                currentObjective = currentObjective ?? string.Empty,
                gameTime = Time.time,
                sceneName = SceneManager.GetActiveScene().name,
                isMoving = hasMoveTarget,
                moveTargetX = moveTarget.x,
                moveTargetZ = moveTarget.z,
                remainingDistance = hasMoveTarget && controlledEntity != null
                    ? Vector3.Distance(position, target)
                    : 0f,
                activeActionId = activeActionId,
                lastActionStatus = lastActionStatus,
                lastChatMessage = lastChatMessage
            };
        }

        private object HandleGetSurroundings(string requestJson)
        {
            Payload payload = ReadPayload(requestJson);
            float radius = payload.radius > 0f
                ? Mathf.Clamp(payload.radius, 0.1f, Mathf.Max(0.1f, maxScanRadius))
                : Mathf.Clamp(defaultScanRadius, 0.1f, Mathf.Max(0.1f, maxScanRadius));
            int maxResults = payload.maxResults > 0
                ? Mathf.Clamp(payload.maxResults, 1, 50)
                : Mathf.Clamp(defaultMaxResults, 1, 50);

            if (controlledEntity == null)
            {
                return new SurroundingsResult
                {
                    radius = radius,
                    count = 0,
                    objects = Array.Empty<SurroundingObjectResult>()
                };
            }

            Collider[] hits = Physics.OverlapSphere(
                controlledEntity.position,
                radius,
                surroundingsMask,
                QueryTriggerInteraction.Collide);

            var unique = new Dictionary<int, SurroundingObjectResult>();

            foreach (Collider hit in hits)
            {
                if (hit == null ||
                    hit.transform == controlledEntity ||
                    hit.transform.IsChildOf(controlledEntity))
                {
                    continue;
                }

                GameObject owner = ResolveTarget(
                    hit.gameObject,
                    out IGameRuntimeMcpInteractable interactable);
                int id = owner.GetInstanceID();
                float distance = Vector3.Distance(
                    controlledEntity.position,
                    owner.transform.position);

                var item = new SurroundingObjectResult
                {
                    targetId = interactable != null
                        ? interactable.RuntimeTargetId
                        : $"instance:{id.ToString(CultureInfo.InvariantCulture)}",
                    name = interactable != null
                        ? interactable.DisplayName
                        : owner.name,
                    tag = owner.tag,
                    distance = distance,
                    worldX = owner.transform.position.x,
                    worldY = owner.transform.position.y,
                    worldZ = owner.transform.position.z,
                    interactable = interactable != null
                };

                if (!unique.TryGetValue(id, out SurroundingObjectResult existing) ||
                    item.distance < existing.distance)
                {
                    unique[id] = item;
                }
            }

            var result = new List<SurroundingObjectResult>(unique.Values);
            result.Sort(
                (left, right) =>
                {
                    int distance = left.distance.CompareTo(right.distance);
                    return distance != 0
                        ? distance
                        : string.Compare(
                            left.targetId,
                            right.targetId,
                            StringComparison.Ordinal);
                });

            if (result.Count > maxResults)
            {
                result.RemoveRange(maxResults, result.Count - maxResults);
            }

            return new SurroundingsResult
            {
                radius = radius,
                count = result.Count,
                objects = result.ToArray()
            };
        }

        private object HandlePlayerMoveTo(string requestJson)
        {
            if (!HasProperty(requestJson, "targetX") ||
                !HasProperty(requestJson, "targetZ"))
            {
                return Reject("invalid_target", "targetX와 targetZ가 필요합니다.");
            }

            Payload payload = ReadPayload(requestJson);
            if (!IsFinite(payload.targetX) || !IsFinite(payload.targetZ))
            {
                return Reject("invalid_target", "이동 좌표는 유한한 숫자여야 합니다.");
            }

            if (controlledEntity == null)
            {
                return Reject("controlled_entity_missing", "제어 대상 Transform이 없습니다.");
            }

            Vector3 target = new Vector3(
                payload.targetX,
                controlledEntity.position.y,
                payload.targetZ);
            float distance = Vector3.Distance(controlledEntity.position, target);

            if (distance > Mathf.Max(0.1f, maxMoveDistance))
            {
                return Reject(
                    "target_too_far",
                    $"한 번의 이동은 {Mathf.Max(0.1f, maxMoveDistance):0.##}m를 넘을 수 없습니다.");
            }

            activeActionId = Guid.NewGuid().ToString("N");
            moveTarget = target;
            hasMoveTarget = distance > Mathf.Max(0f, stoppingDistance);
            lastActionStatus = hasMoveTarget ? "running" : "completed";

            if (!hasMoveTarget)
            {
                controlledEntity.position = target;
            }

            return new ActionResult
            {
                accepted = true,
                code = "accepted",
                message = hasMoveTarget
                    ? "이동을 시작했습니다."
                    : "이미 목표 위치에 있습니다.",
                actionId = activeActionId,
                status = lastActionStatus,
                targetX = payload.targetX,
                targetZ = payload.targetZ
            };
        }

        private object HandlePlayerInteract(string requestJson)
        {
            Payload payload = ReadPayload(requestJson);
            string targetId = payload.targetId?.Trim() ?? string.Empty;
            string targetName = payload.targetName?.Trim() ?? string.Empty;

            if (string.IsNullOrEmpty(targetId) &&
                string.IsNullOrEmpty(targetName))
            {
                return Reject("invalid_target", "targetId 또는 targetName이 필요합니다.");
            }

            if (controlledEntity == null)
            {
                return Reject("controlled_entity_missing", "제어 대상 Transform이 없습니다.");
            }

            float radius = Mathf.Max(0.1f, interactionRadius);
            Collider[] hits = Physics.OverlapSphere(
                controlledEntity.position,
                radius,
                surroundingsMask,
                QueryTriggerInteraction.Collide);

            IGameRuntimeMcpInteractable selected = null;
            GameObject selectedOwner = null;
            float selectedDistance = float.MaxValue;
            var visited = new HashSet<int>();

            foreach (Collider hit in hits)
            {
                if (hit == null ||
                    hit.transform == controlledEntity ||
                    hit.transform.IsChildOf(controlledEntity))
                {
                    continue;
                }

                GameObject owner = ResolveTarget(
                    hit.gameObject,
                    out IGameRuntimeMcpInteractable interactable);

                if (interactable == null || !visited.Add(owner.GetInstanceID()))
                {
                    continue;
                }

                bool match = !string.IsNullOrEmpty(targetId)
                    ? interactable.RuntimeTargetId == targetId
                    : string.Equals(
                        interactable.DisplayName,
                        targetName,
                        StringComparison.OrdinalIgnoreCase);

                if (!match)
                {
                    continue;
                }

                float distance = Vector3.Distance(
                    controlledEntity.position,
                    owner.transform.position);

                if (distance < selectedDistance)
                {
                    selected = interactable;
                    selectedOwner = owner;
                    selectedDistance = distance;
                }
            }

            if (selected == null || selectedOwner == null)
            {
                return Reject(
                    "target_not_found",
                    $"상호작용 반경 {radius:0.##}m 안에서 대상을 찾지 못했습니다.",
                    targetId,
                    targetName);
            }

            bool success = selected.TryInteract(
                controlledEntity.gameObject,
                out string message);

            return new ActionResult
            {
                accepted = success,
                code = success ? "completed" : "rejected",
                message = message ?? string.Empty,
                targetId = selected.RuntimeTargetId,
                targetName = selected.DisplayName,
                status = success ? "completed" : "rejected"
            };
        }

        private object HandleSendInGameChat(string requestJson)
        {
            Payload payload = ReadPayload(requestJson);
            string message = payload.message?.Trim() ?? string.Empty;

            if (string.IsNullOrEmpty(message))
            {
                return Reject("empty_message", "message가 비어 있습니다.");
            }

            if (message.Length > 500)
            {
                return Reject("message_too_long", "인게임 채팅은 500자를 넘을 수 없습니다.");
            }

            lastChatMessage = message;
            onChatMessage?.Invoke(message);
            Debug.Log($"[Game Chat] [AI Agent] {message}", this);

            return new ActionResult
            {
                accepted = true,
                code = "completed",
                message = "인게임 채팅 전달을 완료했습니다.",
                status = "completed"
            };
        }

        private static Payload ReadPayload(string requestJson)
        {
            RequestEnvelope request =
                JsonUtility.FromJson<RequestEnvelope>(requestJson);
            return request != null && request.payload != null
                ? request.payload
                : new Payload();
        }

        private static ActionResult Reject(
            string code,
            string message,
            string targetId = "",
            string targetName = "")
        {
            return new ActionResult
            {
                accepted = false,
                code = code,
                message = message,
                status = "rejected",
                targetId = targetId,
                targetName = targetName
            };
        }

        private static GameObject ResolveTarget(
            GameObject source,
            out IGameRuntimeMcpInteractable interactable)
        {
            MonoBehaviour[] behaviours =
                source.GetComponentsInParent<MonoBehaviour>(true);

            foreach (MonoBehaviour behaviour in behaviours)
            {
                if (behaviour is IGameRuntimeMcpInteractable candidate)
                {
                    interactable = candidate;
                    return behaviour.gameObject;
                }
            }

            interactable = null;
            return source;
        }

        private static bool HasProperty(string json, string propertyName)
        {
            return !string.IsNullOrEmpty(json) &&
                   json.IndexOf(
                       $"\"{propertyName}\"",
                       StringComparison.Ordinal) >= 0;
        }

        private static bool IsFinite(float value)
        {
            return !float.IsNaN(value) && !float.IsInfinity(value);
        }
    }
}
