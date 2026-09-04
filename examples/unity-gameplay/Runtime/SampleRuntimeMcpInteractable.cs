using System.Globalization;
using UnityEngine;

namespace GameRuntimeMcp
{
    public interface IGameRuntimeMcpInteractable
    {
        string RuntimeTargetId { get; }
        string DisplayName { get; }
        bool TryInteract(GameObject actor, out string message);
    }

    [DisallowMultipleComponent]
    public sealed class SampleRuntimeMcpInteractable :
        MonoBehaviour,
        IGameRuntimeMcpInteractable
    {
        [SerializeField] private string runtimeTargetId = string.Empty;
        [SerializeField] private string displayName = string.Empty;
        [SerializeField] private string interactionMessage = "상호작용을 완료했습니다.";

        public int InteractionCount { get; private set; }

        public string RuntimeTargetId =>
            string.IsNullOrWhiteSpace(runtimeTargetId)
                ? $"instance:{gameObject.GetInstanceID().ToString(CultureInfo.InvariantCulture)}"
                : runtimeTargetId.Trim();

        public string DisplayName =>
            string.IsNullOrWhiteSpace(displayName)
                ? gameObject.name
                : displayName.Trim();

        public bool TryInteract(GameObject actor, out string message)
        {
            InteractionCount++;
            message = interactionMessage ?? string.Empty;

            Debug.Log(
                $"[Runtime MCP Sample] '{actor?.name ?? "Unknown"}' -> " +
                $"'{DisplayName}' 상호작용 #{InteractionCount}",
                this);

            return true;
        }
    }
}
