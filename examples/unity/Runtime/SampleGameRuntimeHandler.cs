using System;
using System.Collections.Generic;
using System.Globalization;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.SceneManagement;

namespace lLCroweTool.GameRuntimeMcpHost
{
    /// <summary>
    /// LLM이 게임 상태를 관찰하고 제한된 플레이 명령을 호출하는 샘플입니다.
    /// 실제 프로젝트에서는 각 명령을 프로젝트의 권위 있는 게임 서비스에 연결합니다.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class SampleGameRuntimeHandler : MonoBehaviour
    {
        /// <summary>
        /// 현재 게임 상태 조회 명령입니다.
        /// </summary>
        public const string GetGameStateCommand = "game.get_state";

        /// <summary>
        /// 제어 대상 주변 조회 명령입니다.
        /// </summary>
        public const string GetSurroundingsCommand = "game.get_surroundings";

        /// <summary>
        /// 월드 X/Z 좌표 이동 명령입니다.
        /// </summary>
        public const string PlayerMoveToCommand = "player.move_to";

        /// <summary>
        /// 주변 대상 상호작용 명령입니다.
        /// </summary>
        public const string PlayerInteractCommand = "player.interact";

        /// <summary>
        /// 게임 소유 채팅 이벤트 전달 명령입니다.
        /// </summary>
        public const string SendInGameChatCommand = "chat.send";

        /// <summary>
        /// 게임 채팅 문자열을 프로젝트 코드에 전달하는 UnityEvent입니다.
        /// </summary>
        [Serializable]
        public sealed class ChatMessageEvent : UnityEvent<string>
        {
        }

        /// <summary>
        /// 제어 대상의 현재 게임 상태입니다.
        /// </summary>
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

        /// <summary>
        /// 주변 조회에서 반환하는 객체 한 건입니다.
        /// </summary>
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

        /// <summary>
        /// 제한된 주변 객체 조회 결과입니다.
        /// </summary>
        [Serializable]
        public sealed class SurroundingsResult
        {
            public float radius;
            public int count;
            public SurroundingObjectResult[] objects;
        }

        /// <summary>
        /// 이동·상호작용·채팅 요청 결과입니다.
        /// </summary>
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

        [Header("런타임 연결")]
        [SerializeField] private GameRuntimeMcpBridge bridge;

        [Header("제어 대상")]
        [SerializeField] private Transform controlledEntity;
        [SerializeField, Min(0.01f)] private float moveSpeed = 5f;
        [SerializeField, Min(0f)] private float stoppingDistance = 0.05f;
        [SerializeField, Min(0.1f)] private float maxMoveDistance = 100f;

        [Header("주변 관찰")]
        [SerializeField, Min(0.1f)] private float defaultScanRadius = 15f;
        [SerializeField, Min(0.1f)] private float maxScanRadius = 50f;
        [SerializeField, Range(1, 50)] private int defaultMaxResults = 10;
        [SerializeField] private LayerMask surroundingsMask = ~0;

        [Header("상호작용")]
        [SerializeField, Min(0.1f)] private float interactionRadius = 5f;

        [Header("샘플 상태")]
        [SerializeField, Min(0)] private int health = 100;
        [SerializeField, Min(1)] private int maxHealth = 100;
        [SerializeField] private string currentObjective =
            "현재 지역을 탐색하고 목표를 확인합니다.";
        [SerializeField] private ChatMessageEvent onChatMessage =
            new ChatMessageEvent();

        private GameRuntimeMcpBridge.CommandBinding[] bindingList;
        private bool registered;
        private float nextRegistrationRetryTime;

        private bool hasMoveTarget;
        private Vector3 moveTarget;
        private string activeActionId = string.Empty;
        private string lastActionStatus = "idle";
        private string lastChatMessage = string.Empty;

        /// <summary>
        /// LLM 명령이 관찰·조작할 Transform입니다.
        /// </summary>
        public Transform ControlledEntity
        {
            get => controlledEntity;
            set => controlledEntity = value;
        }

        /// <summary>
        /// 샘플 Transform 이동 속도입니다.
        /// </summary>
        public float MoveSpeed
        {
            get => moveSpeed;
            set => moveSpeed = Mathf.Max(0.01f, value);
        }

        /// <summary>
        /// 가장 최근에 전달된 채팅 메시지입니다.
        /// </summary>
        public string LastChatMessage => lastChatMessage;

        private void Awake()
        {
            if (controlledEntity == null)
            {
                controlledEntity = transform;
            }

            bindingList = new[]
            {
                GameRuntimeMcpBridge.Bind(
                    GetGameStateCommand,
                    HandleGetGameState),
                GameRuntimeMcpBridge.Bind(
                    GetSurroundingsCommand,
                    HandleGetSurroundings),
                GameRuntimeMcpBridge.Bind(
                    PlayerMoveToCommand,
                    HandlePlayerMoveTo),
                GameRuntimeMcpBridge.Bind(
                    PlayerInteractCommand,
                    HandlePlayerInteract),
                GameRuntimeMcpBridge.Bind(
                    SendInGameChatCommand,
                    HandleSendInGameChat)
            };
        }

        private void OnEnable()
        {
            nextRegistrationRetryTime = 0f;
            TryRegister();
        }

        private void Update()
        {
            if (registered && bridge == null)
            {
                registered = false;
            }

            if (!registered &&
                Time.unscaledTime >= nextRegistrationRetryTime)
            {
                TryRegister();
            }

            UpdateMovement();
        }

        private void OnDisable()
        {
            if (bridge != null)
            {
                bridge.UnregisterAll(this);
            }

            registered = false;
            bridge = null;
        }

        private void TryRegister()
        {
            if (registered)
            {
                return;
            }

            if (bridge == null)
            {
                bridge = GameRuntimeMcpBridge.Instance;
            }

            if (bridge == null)
            {
                nextRegistrationRetryTime =
                    Time.unscaledTime + 0.5f;
                return;
            }

            registered = bridge.RegisterAll(
                this,
                out string error,
                bindingList);

            if (registered)
            {
                return;
            }

            nextRegistrationRetryTime =
                Time.unscaledTime + 2f;

            Debug.LogWarning(
                $"[Runtime MCP Sample] 명령 등록 실패: {error}",
                this);

            bridge = null;
        }

        private void UpdateMovement()
        {
            if (!hasMoveTarget ||
                controlledEntity == null)
            {
                return;
            }

            Vector3 current = controlledEntity.position;
            Vector3 target = new Vector3(
                moveTarget.x,
                current.y,
                moveTarget.z);

            float stop = Mathf.Max(0f, stoppingDistance);

            if (Vector3.Distance(current, target) <= stop)
            {
                controlledEntity.position = target;
                hasMoveTarget = false;
                lastActionStatus = "completed";
                return;
            }

            controlledEntity.position =
                Vector3.MoveTowards(
                    current,
                    target,
                    Mathf.Max(0.01f, moveSpeed) *
                    Time.deltaTime);
        }

        private GameRuntimeMcpBridge.RuntimeCommandResult
            HandleGetGameState(string requestJson)
        {
            Vector3 position = controlledEntity != null
                ? controlledEntity.position
                : Vector3.zero;

            Vector3 target = new Vector3(
                moveTarget.x,
                position.y,
                moveTarget.z);

            return GameRuntimeMcpBridge.RuntimeCommandResult.Ok(
                new GameStateResult
                {
                    entityName = controlledEntity != null
                        ? controlledEntity.name
                        : "Unknown",
                    positionX = position.x,
                    positionY = position.y,
                    positionZ = position.z,
                    health = Mathf.Clamp(
                        health,
                        0,
                        Mathf.Max(1, maxHealth)),
                    maxHealth = Mathf.Max(1, maxHealth),
                    currentObjective =
                        currentObjective ?? string.Empty,
                    gameTime = Time.time,
                    sceneName =
                        SceneManager.GetActiveScene().name,
                    isMoving = hasMoveTarget,
                    moveTargetX = moveTarget.x,
                    moveTargetZ = moveTarget.z,
                    remainingDistance =
                        hasMoveTarget &&
                        controlledEntity != null
                            ? Vector3.Distance(position, target)
                            : 0f,
                    activeActionId = activeActionId,
                    lastActionStatus = lastActionStatus,
                    lastChatMessage = lastChatMessage
                });
        }

        private GameRuntimeMcpBridge.RuntimeCommandResult
            HandleGetSurroundings(string requestJson)
        {
            Payload payload = ReadPayload(requestJson);

            float radius = payload.radius > 0f
                ? Mathf.Clamp(
                    payload.radius,
                    0.1f,
                    Mathf.Max(0.1f, maxScanRadius))
                : Mathf.Clamp(
                    defaultScanRadius,
                    0.1f,
                    Mathf.Max(0.1f, maxScanRadius));

            int resultLimit = payload.maxResults > 0
                ? Mathf.Clamp(payload.maxResults, 1, 50)
                : Mathf.Clamp(defaultMaxResults, 1, 50);

            if (controlledEntity == null)
            {
                return GameRuntimeMcpBridge.RuntimeCommandResult.Ok(
                    new SurroundingsResult
                    {
                        radius = radius,
                        count = 0,
                        objects =
                            Array.Empty<SurroundingObjectResult>()
                    });
            }

            Collider[] hits = Physics.OverlapSphere(
                controlledEntity.position,
                radius,
                surroundingsMask,
                QueryTriggerInteraction.Collide);

            var uniqueMap =
                new Dictionary<int, SurroundingObjectResult>();

            foreach (Collider hit in hits)
            {
                if (ShouldIgnore(hit))
                {
                    continue;
                }

                GameObject owner = ResolveTarget(
                    hit.gameObject,
                    out IGameRuntimeMcpInteractable interactable);

                int instanceId = owner.GetInstanceID();

                var item = new SurroundingObjectResult
                {
                    targetId = interactable != null
                        ? interactable.RuntimeTargetId
                        : "instance:" +
                          instanceId.ToString(
                              CultureInfo.InvariantCulture),
                    name = interactable != null
                        ? interactable.DisplayName
                        : owner.name,
                    tag = owner.tag,
                    distance = Vector3.Distance(
                        controlledEntity.position,
                        owner.transform.position),
                    worldX = owner.transform.position.x,
                    worldY = owner.transform.position.y,
                    worldZ = owner.transform.position.z,
                    interactable = interactable != null
                };

                if (!uniqueMap.TryGetValue(
                        instanceId,
                        out SurroundingObjectResult existing) ||
                    item.distance < existing.distance)
                {
                    uniqueMap[instanceId] = item;
                }
            }

            var resultList =
                new List<SurroundingObjectResult>(
                    uniqueMap.Values);

            resultList.Sort(CompareSurroundings);

            if (resultList.Count > resultLimit)
            {
                resultList.RemoveRange(
                    resultLimit,
                    resultList.Count - resultLimit);
            }

            return GameRuntimeMcpBridge.RuntimeCommandResult.Ok(
                new SurroundingsResult
                {
                    radius = radius,
                    count = resultList.Count,
                    objects = resultList.ToArray()
                });
        }

        private GameRuntimeMcpBridge.RuntimeCommandResult
            HandlePlayerMoveTo(string requestJson)
        {
            if (!HasProperty(requestJson, "targetX") ||
                !HasProperty(requestJson, "targetZ"))
            {
                return Reject(
                    "invalid_target",
                    "targetX와 targetZ가 필요합니다.");
            }

            Payload payload = ReadPayload(requestJson);

            if (!IsFinite(payload.targetX) ||
                !IsFinite(payload.targetZ))
            {
                return Reject(
                    "invalid_target",
                    "이동 좌표는 유한한 숫자여야 합니다.");
            }

            if (controlledEntity == null)
            {
                return Reject(
                    "controlled_entity_missing",
                    "제어 대상 Transform이 없습니다.");
            }

            Vector3 target = new Vector3(
                payload.targetX,
                controlledEntity.position.y,
                payload.targetZ);

            float distance =
                Vector3.Distance(
                    controlledEntity.position,
                    target);

            if (distance > Mathf.Max(0.1f, maxMoveDistance))
            {
                return Reject(
                    "target_too_far",
                    $"한 번의 이동은 " +
                    $"{Mathf.Max(0.1f, maxMoveDistance):0.##}m를 " +
                    "넘을 수 없습니다.");
            }

            activeActionId = Guid.NewGuid().ToString("N");
            moveTarget = target;
            hasMoveTarget =
                distance > Mathf.Max(0f, stoppingDistance);

            lastActionStatus =
                hasMoveTarget ? "running" : "completed";

            if (!hasMoveTarget)
            {
                controlledEntity.position = target;
            }

            return GameRuntimeMcpBridge.RuntimeCommandResult.Ok(
                new ActionResult
                {
                    accepted = true,
                    code = "accepted",
                    message = hasMoveTarget
                        ? "이동 시작"
                        : "목표 위치 도착 상태",
                    actionId = activeActionId,
                    status = lastActionStatus,
                    targetX = payload.targetX,
                    targetZ = payload.targetZ
                });
        }

        private GameRuntimeMcpBridge.RuntimeCommandResult
            HandlePlayerInteract(string requestJson)
        {
            Payload payload = ReadPayload(requestJson);

            string targetId =
                payload.targetId?.Trim() ?? string.Empty;

            string targetName =
                payload.targetName?.Trim() ?? string.Empty;

            if (string.IsNullOrEmpty(targetId) &&
                string.IsNullOrEmpty(targetName))
            {
                return Reject(
                    "invalid_target",
                    "targetId 또는 targetName이 필요합니다.");
            }

            if (controlledEntity == null)
            {
                return Reject(
                    "controlled_entity_missing",
                    "제어 대상 Transform이 없습니다.");
            }

            if (!TryFindInteractable(
                    targetId,
                    targetName,
                    out IGameRuntimeMcpInteractable interactable))
            {
                return Reject(
                    "target_not_found",
                    "상호작용 반경 안에서 대상을 찾지 못했습니다.");
            }

            bool success = interactable.TryInteract(
                controlledEntity.gameObject,
                out string message);

            activeActionId = Guid.NewGuid().ToString("N");
            lastActionStatus =
                success ? "completed" : "rejected";

            return GameRuntimeMcpBridge.RuntimeCommandResult.Ok(
                new ActionResult
                {
                    accepted = success,
                    code = success
                        ? "completed"
                        : "interaction_rejected",
                    message = message ?? string.Empty,
                    actionId = activeActionId,
                    status = lastActionStatus,
                    targetId = interactable.RuntimeTargetId,
                    targetName = interactable.DisplayName
                });
        }

        private GameRuntimeMcpBridge.RuntimeCommandResult
            HandleSendInGameChat(string requestJson)
        {
            if (!HasProperty(requestJson, "message"))
            {
                return Reject(
                    "message_required",
                    "message가 필요합니다.");
            }

            Payload payload = ReadPayload(requestJson);
            string message = payload.message?.Trim() ?? string.Empty;

            if (string.IsNullOrEmpty(message))
            {
                return Reject(
                    "message_required",
                    "빈 메시지는 전달할 수 없습니다.");
            }

            if (message.Length > 500)
            {
                return Reject(
                    "message_too_long",
                    "채팅 메시지는 500자를 넘을 수 없습니다.");
            }

            lastChatMessage = message;
            activeActionId = Guid.NewGuid().ToString("N");
            lastActionStatus = "completed";

            onChatMessage.Invoke(message);
            Debug.Log(
                $"[Game Chat] [AI Agent] {message}",
                this);

            return GameRuntimeMcpBridge.RuntimeCommandResult.Ok(
                new ActionResult
                {
                    accepted = true,
                    code = "completed",
                    message = "채팅 메시지 전달 완료",
                    actionId = activeActionId,
                    status = lastActionStatus
                });
        }

        private bool TryFindInteractable(
            string targetId,
            string targetName,
            out IGameRuntimeMcpInteractable selected)
        {
            selected = null;
            float selectedDistance = float.MaxValue;

            Collider[] hits = Physics.OverlapSphere(
                controlledEntity.position,
                Mathf.Max(0.1f, interactionRadius),
                surroundingsMask,
                QueryTriggerInteraction.Collide);

            var visited = new HashSet<int>();

            foreach (Collider hit in hits)
            {
                if (ShouldIgnore(hit))
                {
                    continue;
                }

                GameObject owner = ResolveTarget(
                    hit.gameObject,
                    out IGameRuntimeMcpInteractable interactable);

                if (interactable == null ||
                    !visited.Add(owner.GetInstanceID()))
                {
                    continue;
                }

                bool matched =
                    !string.IsNullOrEmpty(targetId)
                        ? string.Equals(
                            interactable.RuntimeTargetId,
                            targetId,
                            StringComparison.Ordinal)
                        : string.Equals(
                            interactable.DisplayName,
                            targetName,
                            StringComparison.OrdinalIgnoreCase);

                if (!matched)
                {
                    continue;
                }

                float distance = Vector3.Distance(
                    controlledEntity.position,
                    owner.transform.position);

                if (distance < selectedDistance)
                {
                    selected = interactable;
                    selectedDistance = distance;
                }
            }

            return selected != null;
        }

        private bool ShouldIgnore(Collider hit)
        {
            return hit == null ||
                   controlledEntity == null ||
                   hit.transform == controlledEntity ||
                   hit.transform.IsChildOf(controlledEntity);
        }

        private static GameObject ResolveTarget(
            GameObject source,
            out IGameRuntimeMcpInteractable interactable)
        {
            Transform current = source.transform;

            while (current != null)
            {
                MonoBehaviour[] behaviourList =
                    current.GetComponents<MonoBehaviour>();

                for (int index = 0;
                     index < behaviourList.Length;
                     index++)
                {
                    if (behaviourList[index] is
                        IGameRuntimeMcpInteractable found)
                    {
                        interactable = found;
                        return current.gameObject;
                    }
                }

                current = current.parent;
            }

            interactable = null;
            return source;
        }

        private static int CompareSurroundings(
            SurroundingObjectResult left,
            SurroundingObjectResult right)
        {
            int distanceCompare =
                left.distance.CompareTo(right.distance);

            return distanceCompare != 0
                ? distanceCompare
                : string.Compare(
                    left.targetId,
                    right.targetId,
                    StringComparison.Ordinal);
        }

        private static Payload ReadPayload(string requestJson)
        {
            try
            {
                RequestEnvelope request =
                    JsonUtility.FromJson<RequestEnvelope>(
                        requestJson);

                return request?.payload ?? new Payload();
            }
            catch (ArgumentException)
            {
                return new Payload();
            }
        }

        private static bool HasProperty(
            string requestJson,
            string propertyName)
        {
            if (string.IsNullOrEmpty(requestJson))
            {
                return false;
            }

            return requestJson.IndexOf(
                       "\"" + propertyName + "\"",
                       StringComparison.Ordinal) >= 0;
        }

        private static bool IsFinite(float value)
        {
            return !float.IsNaN(value) &&
                   !float.IsInfinity(value);
        }

        private static GameRuntimeMcpBridge.RuntimeCommandResult
            Reject(string code, string message)
        {
            return GameRuntimeMcpBridge.RuntimeCommandResult.Ok(
                new ActionResult
                {
                    accepted = false,
                    code = code,
                    message = message,
                    actionId = string.Empty,
                    status = "rejected"
                });
        }
    }
}
