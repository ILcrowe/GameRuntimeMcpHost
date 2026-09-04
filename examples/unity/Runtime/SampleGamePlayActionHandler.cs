using System;
using System.Collections.Generic;
using System.Globalization;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.SceneManagement;

namespace GameRuntimeMcp
{
    /// <summary>
    /// 상태 조회, 주변 탐색, 이동, 상호작용, 채팅을 한 컴포넌트에 묶은 샘플입니다.
    /// 실제 프로젝트에서는 Handle 메서드 내부만 게임의 권위 서비스로 교체합니다.
    /// </summary>
    [DefaultExecutionOrder(-800)]
    [DisallowMultipleComponent]
    [RequireComponent(typeof(GameRuntimeMcpBridge))]
    public sealed class SampleGamePlayActionHandler : MonoBehaviour
    {
        public const string GetGameStateCommand = "game.get_state";
        public const string GetSurroundingsCommand = "game.get_surroundings";
        public const string MoveToCommand = "player.move_to";
        public const string InteractCommand = "player.interact";
        public const string ChatCommand = "chat.send";

        [Serializable]
        public sealed class ChatEvent : UnityEvent<string>
        {
        }

        [Serializable]
        public sealed class InteractionEvent : UnityEvent<Transform>
        {
        }

        [Serializable]
        public sealed class RuntimeTarget
        {
            public string targetId = "";
            public string displayName = "";
            public string kind = "object";
            public Transform target;
            public bool interactable = true;
            public InteractionEvent onInteract = new InteractionEvent();

            [NonSerialized] private int interactionCount;

            public int InteractionCount => interactionCount;

            public string Id => !string.IsNullOrWhiteSpace(targetId)
                ? targetId.Trim()
                : target != null
                    ? $"target:{target.GetInstanceID().ToString(CultureInfo.InvariantCulture)}"
                    : "";

            public string Name => !string.IsNullOrWhiteSpace(displayName)
                ? displayName.Trim()
                : target != null ? target.name : "";

            public bool Interact(Transform actor, out string message)
            {
                if (!interactable || target == null)
                {
                    message = "상호작용할 수 없는 대상입니다.";
                    return false;
                }

                interactionCount++;
                onInteract?.Invoke(actor);
                message = $"{Name} 상호작용을 실행했습니다.";
                return true;
            }
        }

        [Serializable]
        private sealed class Request
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
        public sealed class GameState
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
            public string lastInteractionTargetId;
            public string lastChatMessage;
        }

        [Serializable]
        public sealed class SurroundingObject
        {
            public string targetId;
            public string name;
            public string kind;
            public string tag;
            public float distance;
            public float worldX;
            public float worldY;
            public float worldZ;
            public bool interactable;
        }

        [Serializable]
        public sealed class Surroundings
        {
            public float radius;
            public int count;
            public SurroundingObject[] objects;
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
        [SerializeField] private List<RuntimeTarget> targetList = new List<RuntimeTarget>();

        [Header("Interaction")]
        [SerializeField, Min(0.1f)] private float interactionRadius = 5f;

        [Header("Sample State")]
        [SerializeField, Min(0)] private int health = 100;
        [SerializeField, Min(1)] private int maxHealth = 100;
        [SerializeField] private string currentObjective = "주변을 확인하고 다음 행동을 선택합니다.";
        [SerializeField] private ChatEvent onChatMessage = new ChatEvent();

        private GameRuntimeMcpBridge bridge;
        private bool registered;
        private bool moving;
        private Vector3 moveTarget;
        private string activeActionId = "";
        private string lastActionStatus = "idle";
        private string lastInteractionTargetId = "";
        private string lastChatMessage = "";

        private GameRuntimeMcpBridge.RuntimeCommandHandler stateHandler;
        private GameRuntimeMcpBridge.RuntimeCommandHandler surroundingsHandler;
        private GameRuntimeMcpBridge.RuntimeCommandHandler moveHandler;
        private GameRuntimeMcpBridge.RuntimeCommandHandler interactHandler;
        private GameRuntimeMcpBridge.RuntimeCommandHandler chatHandler;

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
        public string LastInteractionTargetId => lastInteractionTargetId;
        public IReadOnlyList<RuntimeTarget> TargetList => targetList;

        private void Awake()
        {
            bridge = GetComponent<GameRuntimeMcpBridge>();
            stateHandler = HandleGetGameState;
            surroundingsHandler = HandleGetSurroundings;
            moveHandler = HandleMoveTo;
            interactHandler = HandleInteract;
            chatHandler = HandleChat;

            if (controlledEntity == null)
                controlledEntity = transform;
        }

        private void OnEnable()
        {
            if (Application.isPlaying)
                RegisterCommands();
        }

        private void Update()
        {
            UpdateMovement();
        }

        private void OnDisable()
        {
            UnregisterCommands();
        }

        public RuntimeTarget AddTarget(
            Transform target,
            string targetId = "",
            string displayName = "",
            string kind = "object",
            bool interactable = true)
        {
            if (target == null)
                throw new ArgumentNullException(nameof(target));

            RuntimeTarget existing = FindTarget(target);
            if (existing != null)
                return existing;

            var item = new RuntimeTarget
            {
                target = target,
                targetId = targetId ?? "",
                displayName = displayName ?? "",
                kind = string.IsNullOrWhiteSpace(kind) ? "object" : kind.Trim(),
                interactable = interactable
            };
            targetList.Add(item);
            return item;
        }

        public bool RemoveTarget(Transform target)
        {
            RuntimeTarget item = FindTarget(target);
            return item != null && targetList.Remove(item);
        }

        private void RegisterCommands()
        {
            if (registered || bridge == null)
                return;

            if (!bridge.RegisterHandler(GetGameStateCommand, stateHandler, out string error) ||
                !bridge.RegisterHandler(GetSurroundingsCommand, surroundingsHandler, out error) ||
                !bridge.RegisterHandler(MoveToCommand, moveHandler, out error) ||
                !bridge.RegisterHandler(InteractCommand, interactHandler, out error) ||
                !bridge.RegisterHandler(ChatCommand, chatHandler, out error))
            {
                UnregisterCommands();
                Debug.LogError($"[Runtime Gameplay] 명령 등록 실패: {error}", this);
                return;
            }

            registered = true;
        }

        private void UnregisterCommands()
        {
            if (bridge == null)
                return;

            bridge.UnregisterHandler(GetGameStateCommand, stateHandler);
            bridge.UnregisterHandler(GetSurroundingsCommand, surroundingsHandler);
            bridge.UnregisterHandler(MoveToCommand, moveHandler);
            bridge.UnregisterHandler(InteractCommand, interactHandler);
            bridge.UnregisterHandler(ChatCommand, chatHandler);
            registered = false;
        }

        private void UpdateMovement()
        {
            if (!moving || controlledEntity == null)
                return;

            Vector3 current = controlledEntity.position;
            Vector3 target = new Vector3(moveTarget.x, current.y, moveTarget.z);
            if (Vector3.Distance(current, target) <= Mathf.Max(0f, stoppingDistance))
            {
                controlledEntity.position = target;
                moving = false;
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
            Vector3 position = controlledEntity != null ? controlledEntity.position : Vector3.zero;
            Vector3 target = new Vector3(moveTarget.x, position.y, moveTarget.z);

            return new GameState
            {
                entityName = controlledEntity != null ? controlledEntity.name : "Unknown",
                positionX = position.x,
                positionY = position.y,
                positionZ = position.z,
                health = Mathf.Clamp(health, 0, Mathf.Max(1, maxHealth)),
                maxHealth = Mathf.Max(1, maxHealth),
                currentObjective = currentObjective ?? "",
                gameTime = Time.time,
                sceneName = SceneManager.GetActiveScene().name,
                isMoving = moving,
                moveTargetX = moveTarget.x,
                moveTargetZ = moveTarget.z,
                remainingDistance = moving && controlledEntity != null
                    ? Vector3.Distance(position, target)
                    : 0f,
                activeActionId = activeActionId,
                lastActionStatus = lastActionStatus,
                lastInteractionTargetId = lastInteractionTargetId,
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
                return new Surroundings { radius = radius, objects = Array.Empty<SurroundingObject>() };

            var byId = new Dictionary<int, SurroundingObject>();
            AddTargets(radius, byId);
            AddPhysicsObjects(radius, byId);

            var result = new List<SurroundingObject>(byId.Values);
            result.Sort((a, b) =>
            {
                int distance = a.distance.CompareTo(b.distance);
                return distance != 0
                    ? distance
                    : string.Compare(a.targetId, b.targetId, StringComparison.Ordinal);
            });

            if (result.Count > maxResults)
                result.RemoveRange(maxResults, result.Count - maxResults);

            return new Surroundings
            {
                radius = radius,
                count = result.Count,
                objects = result.ToArray()
            };
        }

        private object HandleMoveTo(string requestJson)
        {
            if (!HasProperty(requestJson, "targetX") || !HasProperty(requestJson, "targetZ"))
                return Reject("invalid_target", "targetX와 targetZ가 필요합니다.");
            if (moving)
                return Reject("action_in_progress", "이전 이동이 끝난 뒤 다시 요청해야 합니다.");
            if (controlledEntity == null)
                return Reject("controlled_entity_missing", "제어 대상 Transform이 없습니다.");

            Payload payload = ReadPayload(requestJson);
            if (!IsFinite(payload.targetX) || !IsFinite(payload.targetZ))
                return Reject("invalid_target", "이동 좌표는 유한한 숫자여야 합니다.");

            Vector3 target = new Vector3(payload.targetX, controlledEntity.position.y, payload.targetZ);
            float distance = Vector3.Distance(controlledEntity.position, target);
            if (distance > Mathf.Max(0.1f, maxMoveDistance))
                return Reject("target_too_far", "한 번의 이동 거리가 제한을 넘었습니다.");

            activeActionId = Guid.NewGuid().ToString("N");
            moveTarget = target;
            moving = distance > Mathf.Max(0f, stoppingDistance);
            lastActionStatus = moving ? "running" : "completed";
            if (!moving)
                controlledEntity.position = target;

            return Accept(
                "move_accepted",
                moving ? "이동을 시작했습니다." : "이미 목표 위치입니다.",
                activeActionId,
                lastActionStatus,
                targetX: target.x,
                targetZ: target.z);
        }

        private object HandleInteract(string requestJson)
        {
            if (moving)
                return Reject("actor_moving", "이동을 마친 뒤 상호작용해야 합니다.");
            if (controlledEntity == null)
                return Reject("controlled_entity_missing", "제어 대상 Transform이 없습니다.");

            Payload payload = ReadPayload(requestJson);
            RuntimeTarget target = FindTarget(payload.targetId, payload.targetName);
            if (target == null || target.target == null)
                return Reject("target_not_found", "등록된 상호작용 대상을 찾지 못했습니다.");
            if (!target.interactable)
                return Reject("target_not_interactable", "상호작용할 수 없는 대상입니다.");

            float distance = Vector3.Distance(controlledEntity.position, target.target.position);
            if (distance > Mathf.Max(0.1f, interactionRadius))
                return Reject("target_out_of_range", $"대상이 너무 멉니다: {distance:0.##}m");
            if (!target.Interact(controlledEntity, out string message))
                return Reject("interaction_rejected", message);

            activeActionId = Guid.NewGuid().ToString("N");
            lastActionStatus = "completed";
            lastInteractionTargetId = target.Id;
            return Accept(
                "interaction_completed",
                message,
                activeActionId,
                "completed",
                target.Id,
                target.Name);
        }

        private object HandleChat(string requestJson)
        {
            string message = ReadPayload(requestJson).message?.Trim() ?? "";
            if (string.IsNullOrEmpty(message))
                return Reject("message_required", "채팅 메시지가 필요합니다.");
            if (message.Length > 500)
                return Reject("message_too_long", "채팅 메시지는 500자를 넘을 수 없습니다.");

            lastChatMessage = message;
            onChatMessage?.Invoke(message);
            Debug.Log($"[Game Chat] [AI Agent] {message}", this);

            activeActionId = Guid.NewGuid().ToString("N");
            lastActionStatus = "completed";
            return Accept("chat_sent", "채팅 메시지를 전달했습니다.", activeActionId, "completed");
        }

        private void AddTargets(float radius, IDictionary<int, SurroundingObject> result)
        {
            for (int i = 0; i < targetList.Count; i++)
            {
                RuntimeTarget target = targetList[i];
                if (target == null || target.target == null)
                    continue;

                float distance = Vector3.Distance(controlledEntity.position, target.target.position);
                if (distance <= radius)
                    result[target.target.GetInstanceID()] = CreateResult(target.target, target, distance);
            }
        }

        private void AddPhysicsObjects(float radius, IDictionary<int, SurroundingObject> result)
        {
            Collider[] hits = Physics.OverlapSphere(
                controlledEntity.position,
                radius,
                surroundingsMask,
                QueryTriggerInteraction.Collide);

            for (int i = 0; i < hits.Length; i++)
            {
                Collider hit = hits[i];
                if (hit == null || hit.transform == controlledEntity || hit.transform.IsChildOf(controlledEntity))
                    continue;

                RuntimeTarget configured = FindTargetInParents(hit.transform);
                Transform target = configured?.target ?? hit.transform;
                int id = target.GetInstanceID();
                float distance = Vector3.Distance(controlledEntity.position, target.position);
                SurroundingObject item = CreateResult(target, configured, distance);

                if (!result.TryGetValue(id, out SurroundingObject prior) || distance < prior.distance)
                    result[id] = item;
            }
        }

        private static SurroundingObject CreateResult(
            Transform transform,
            RuntimeTarget configured,
            float distance)
        {
            return new SurroundingObject
            {
                targetId = configured != null
                    ? configured.Id
                    : $"instance:{transform.GetInstanceID().ToString(CultureInfo.InvariantCulture)}",
                name = configured != null ? configured.Name : transform.name,
                kind = configured != null ? configured.kind : "object",
                tag = transform.gameObject.tag,
                distance = distance,
                worldX = transform.position.x,
                worldY = transform.position.y,
                worldZ = transform.position.z,
                interactable = configured != null && configured.interactable
            };
        }

        private RuntimeTarget FindTarget(Transform transform)
        {
            for (int i = 0; i < targetList.Count; i++)
            {
                RuntimeTarget item = targetList[i];
                if (item != null && item.target == transform)
                    return item;
            }
            return null;
        }

        private RuntimeTarget FindTarget(string id, string name)
        {
            id = id?.Trim() ?? "";
            name = name?.Trim() ?? "";

            for (int i = 0; i < targetList.Count; i++)
            {
                RuntimeTarget item = targetList[i];
                if (item == null || item.target == null)
                    continue;
                if (!string.IsNullOrEmpty(id) && string.Equals(item.Id, id, StringComparison.Ordinal))
                    return item;
                if (string.IsNullOrEmpty(id) && !string.IsNullOrEmpty(name) &&
                    string.Equals(item.Name, name, StringComparison.OrdinalIgnoreCase))
                    return item;
            }
            return null;
        }

        private RuntimeTarget FindTargetInParents(Transform transform)
        {
            while (transform != null)
            {
                RuntimeTarget item = FindTarget(transform);
                if (item != null)
                    return item;
                transform = transform.parent;
            }
            return null;
        }

        private static Payload ReadPayload(string json)
        {
            try
            {
                Request request = JsonUtility.FromJson<Request>(json);
                return request?.payload ?? new Payload();
            }
            catch (ArgumentException)
            {
                return new Payload();
            }
        }

        private static bool HasProperty(string json, string name)
        {
            return !string.IsNullOrEmpty(json) &&
                   json.IndexOf($"\"{name}\"", StringComparison.Ordinal) >= 0;
        }

        private static bool IsFinite(float value)
        {
            return !float.IsNaN(value) && !float.IsInfinity(value);
        }

        private static ActionResult Accept(
            string code,
            string message,
            string actionId,
            string status,
            string targetId = "",
            string targetName = "",
            float targetX = 0f,
            float targetZ = 0f)
        {
            return new ActionResult
            {
                accepted = true,
                code = code,
                message = message,
                actionId = actionId,
                status = status,
                targetId = targetId,
                targetName = targetName,
                targetX = targetX,
                targetZ = targetZ
            };
        }

        private static ActionResult Reject(string code, string message)
        {
            return new ActionResult
            {
                accepted = false,
                code = code,
                message = message,
                status = "rejected"
            };
        }
    }
}
