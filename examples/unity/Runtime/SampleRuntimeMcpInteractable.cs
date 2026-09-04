using System;
using UnityEngine;
using UnityEngine.Events;

namespace lLCroweTool.GameRuntimeMcpHost
{
    /// <summary>
    /// 런타임 MCP를 통해 호출할 수 있는 게임 상호작용 계약입니다.
    /// 실제 프로젝트에서는 기존 상호작용 서비스나 인터페이스로 교체합니다.
    /// </summary>
    public interface IGameRuntimeMcpInteractable
    {
        /// <summary>
        /// 같은 런타임 세션에서 대상을 식별하는 ID입니다.
        /// </summary>
        string RuntimeTargetId { get; }

        /// <summary>
        /// LLM과 사용자에게 표시할 대상 이름입니다.
        /// </summary>
        string DisplayName { get; }

        /// <summary>
        /// 지정한 행위자의 상호작용을 게임 규칙에 따라 처리합니다.
        /// </summary>
        bool TryInteract(GameObject actor, out string message);
    }

    /// <summary>
    /// Collider가 있는 GameObject에 붙여 사용하는 최소 상호작용 샘플입니다.
    /// Unity에서 바로 추가할 수 있도록 MonoBehaviour 이름과 파일 이름을 일치시킵니다.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class SampleRuntimeMcpInteractable :
        MonoBehaviour,
        IGameRuntimeMcpInteractable
    {
        /// <summary>
        /// 상호작용이 발생했을 때 호출되는 UnityEvent입니다.
        /// </summary>
        [Serializable]
        public sealed class InteractionEvent : UnityEvent<GameObject>
        {
        }

        [Header("런타임 상호작용")]
        [SerializeField] private string runtimeTargetId;
        [SerializeField] private string displayName;
        [SerializeField] private string successMessage =
            "상호작용 완료";
        [SerializeField] private InteractionEvent onInteract =
            new InteractionEvent();

        private int interactionCount;

        /// <summary>
        /// 명시값이 없으면 현재 GameObject Instance ID를 사용합니다.
        /// </summary>
        public string RuntimeTargetId =>
            string.IsNullOrWhiteSpace(runtimeTargetId)
                ? $"instance:{gameObject.GetInstanceID()}"
                : runtimeTargetId.Trim();

        /// <summary>
        /// 명시값이 없으면 현재 GameObject 이름을 사용합니다.
        /// </summary>
        public string DisplayName =>
            string.IsNullOrWhiteSpace(displayName)
                ? gameObject.name
                : displayName.Trim();

        /// <summary>
        /// 현재 실행에서 처리한 상호작용 횟수입니다.
        /// </summary>
        public int InteractionCount => interactionCount;

        /// <summary>
        /// 샘플 상호작용을 처리하고 UnityEvent를 호출합니다.
        /// </summary>
        public bool TryInteract(
            GameObject actor,
            out string message)
        {
            interactionCount++;
            onInteract.Invoke(actor);

            message = string.IsNullOrWhiteSpace(successMessage)
                ? $"{DisplayName} 상호작용 완료"
                : successMessage;

            Debug.Log(
                $"[Runtime MCP Sample] {DisplayName}: {message}",
                this);

            return true;
        }
    }
}
