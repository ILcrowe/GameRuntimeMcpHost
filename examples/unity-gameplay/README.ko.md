# Unity 게임 플레이 런타임 MCP 샘플

[English guide](README.md)

이 샘플은 Claude, Grok, Codex 같은 MCP 클라이언트가 실행 중인 Unity 게임에 접속해 **게임 상태를 관찰하고, 명시적으로 허용된 게임 플레이 명령을 호출**하는 최소 구조를 제공합니다.

```text
MCP 클라이언트
  -> stdio JSON-RPC
  -> GameRuntimeMcpHost
  -> HTTP POST 127.0.0.1:{port}/rpc + 세션 토큰
  -> GameRuntimeMcpBridge
  -> SampleGamePlayActionHandler
  -> 게임 상태·이동·상호작용·채팅
```

`GameRuntimeMcpHost`는 전송만 담당합니다. 실제 상태, 이동 가능 여부, 상호작용 조건, 채팅 전달의 최종 권한은 Unity 게임 코드에 남습니다.

## 구성 파일

| 파일 | 역할 |
|---|---|
| [`Runtime/GameRuntimeMcpBridge.cs`](Runtime/GameRuntimeMcpBridge.cs) | 루프백 Listener, 세션 파일, 토큰 인증, 제한된 메인 스레드 디스패치 |
| [`Runtime/SampleGamePlayActionHandler.cs`](Runtime/SampleGamePlayActionHandler.cs) | 게임 상태 조회, 주변 탐색, 이동, 상호작용, 채팅 샘플 |
| [`Runtime/SampleRuntimeMcpInteractable.cs`](Runtime/SampleRuntimeMcpInteractable.cs) | 명시적인 상호작용 대상 인터페이스와 샘플 구현 |
| [`game-runtime.tools.json`](game-runtime.tools.json) | MCP 도구 이름·설명·입력 JSON Schema와 RPC 명령 매핑 |
| [`Tests/GameRuntimeMcpBridgeTests.cs`](Tests/GameRuntimeMcpBridgeTests.cs) | 인증·상태·주변 탐색·이동·상호작용·채팅 PlayMode 왕복 검증 |

## 중요: 기존 Unity 샘플과 동시에 설치하지 않기

이 폴더는 [`../unity`](../unity)의 `UnityRuntimeMcpSampleBridge`와 **대체 관계인 독립 샘플**입니다.

한 프로젝트의 같은 실행 경로에는 다음 중 하나만 둡니다.

```text
A. examples/unity
   -> 최소 Bridge + 범용 진단 샘플

B. examples/unity-gameplay
   -> 등록형 Bridge + 게임 플레이 샘플
```

둘을 동시에 활성화하면 세션 파일·포트·런타임 대상이 중복될 수 있습니다.

## 제공 도구

| MCP 도구 | RPC 명령 | 역할 |
|---|---|---|
| `runtime_status` | `runtime.status` | 연결된 Player·프로세스·씬 상태 확인 |
| `get_game_state` | `game.get_state` | 위치·체력·목표·이동 상태 조회 |
| `get_surroundings` | `game.get_surroundings` | 주변 객체와 상호작용 가능 대상 조회 |
| `player_move_to` | `player.move_to` | X/Z 목표 위치로 이동 요청 |
| `player_interact` | `player.interact` | `targetId` 우선 상호작용 |
| `send_in_game_chat` | `chat.send` | 게임 소유 채팅 이벤트로 메시지 전달 |

## 1. Unity 프로젝트에 복사

다음 폴더를 Unity 프로젝트에 복사합니다.

```text
Assets/GameRuntimeMcpGameplaySample/
├─ Runtime/
│  ├─ GameRuntimeMcpBridge.cs
│  ├─ SampleGamePlayActionHandler.cs
│  ├─ SampleRuntimeMcpInteractable.cs
│  └─ lLCroweTool.GameRuntimeMcpHost.GameplaySample.asmdef
└─ Tests/                                  # 선택
   ├─ GameRuntimeMcpBridgeTests.cs
   └─ lLCroweTool.GameRuntimeMcpHost.GameplaySample.Tests.asmdef
```

## 2. Boot Scene에 배치

```text
Boot Scene
├─ RuntimeServices
│  └─ GameRuntimeMcpBridge
└─ ControlledEntity
   └─ SampleGamePlayActionHandler
```

`SampleGamePlayActionHandler.Controlled Entity`에 실제 조작 대상을 연결합니다.

샘플 상호작용을 확인하려면 Collider가 있는 GameObject에 `SampleRuntimeMcpInteractable`을 추가합니다.

### 샘플의 실제 동작

- `player_move_to`는 `Vector3.MoveTowards`로 대상을 실제 이동시킵니다.
- `get_game_state`는 이동 중 여부, 목표 좌표, 남은 거리, 마지막 Action 상태를 함께 반환합니다.
- `get_surroundings`는 3D `Physics.OverlapSphere`를 사용하고 거리순으로 제한된 결과만 반환합니다.
- `player_interact`는 주변 반경 안의 `IGameRuntimeMcpInteractable` 구현만 호출합니다.
- `send_in_game_chat`는 `onChatMessage` UnityEvent와 Console Log에 메시지를 전달합니다.

상용 프로젝트에서는 직접 Transform 이동, 샘플 체력·목표, 샘플 상호작용을 각각 프로젝트의 권위 서비스로 교체합니다.

커스텀 핸들러 반환값은 `JsonUtility`가 직렬화할 수 있는 `[Serializable]` 클래스와 public field DTO를 사용합니다. 익명 타입이나 property-only 객체는 이 샘플의 기본 직렬화 계약으로 취급하지 않습니다.

## 3. Host 설치 및 실행

저장소 루트에서 설치합니다.

```powershell
python -m pip install -e .
```

Unity Play Mode 또는 Desktop Player를 실행하면 다음 세션 파일이 `Application.persistentDataPath`에 생성됩니다.

```text
game-runtime-mcp-session.json
```

자동 탐색으로 Host를 실행합니다.

```powershell
game-runtime-mcp-host `
  --session-name game-runtime-mcp-session.json `
  --session-product UnityGameRuntime `
  --tools-file C:\path\to\GameRuntimeMcpHost\examples\unity-gameplay\game-runtime.tools.json
```

Host를 게임보다 먼저 실행해도 됩니다. 다음 Tool 호출 때 최신 세션 파일을 다시 탐색합니다.

## MCP 클라이언트 공통 설정 예시

Claude Desktop, Cursor 등 stdio MCP 서버 등록을 지원하는 클라이언트에는 다음 형태로 등록합니다. 실제 저장소 경로만 교체합니다.

```json
{
  "mcpServers": {
    "unity-game-runtime": {
      "command": "python",
      "args": [
        "-X",
        "utf8",
        "C:/path/to/GameRuntimeMcpHost/src/game_runtime_mcp_host.py",
        "--session-name",
        "game-runtime-mcp-session.json",
        "--session-product",
        "UnityGameRuntime",
        "--tools-file",
        "C:/path/to/GameRuntimeMcpHost/examples/unity-gameplay/game-runtime.tools.json"
      ],
      "env": {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1"
      }
    }
  }
}
```

## Codex MCP 등록 예시

```powershell
codex mcp add unity_game_runtime `
  --env PYTHONIOENCODING=utf-8 `
  --env PYTHONUTF8=1 `
  -- python -X utf8 C:\path\to\GameRuntimeMcpHost\src\game_runtime_mcp_host.py `
  --session-name game-runtime-mcp-session.json `
  --session-product UnityGameRuntime `
  --tools-file C:\path\to\GameRuntimeMcpHost\examples\unity-gameplay\game-runtime.tools.json
```

등록을 바꾼 뒤에는 새 클라이언트 세션을 엽니다.

## 낮은 추론량 Skill 설치

저장소의 런타임 Skill을 Unity 프로젝트에 설치합니다.

```powershell
& "C:\path\to\GameRuntimeMcpHost\skills\install-codex.ps1" `
  -TargetProject "C:\path\to\YourUnityProject"
```

설치 뒤 새 Codex 세션을 엽니다. Skill은 다음 호출 순서와 Timeout 재시도 금지 규칙을 제공합니다.

## 낮은 추론량 권장 호출 순서

```text
runtime_status
  -> get_game_state
  -> get_surroundings
  -> player_move_to
  -> get_game_state로 이동 상태 재확인
  -> get_surroundings로 대상 재확인
  -> player_interact
  -> 게임별 권위 상태로 최종 확인
```

채팅 요청은 다른 상태 변경 검증과 분리해서 `send_in_game_chat`을 호출합니다.

## Tool 호출 예

### 상태 조회

```json
{}
```

### 주변 탐색

```json
{
  "radius": 12,
  "maxResults": 10
}
```

### 이동

```json
{
  "targetX": 8.5,
  "targetZ": -3.0
}
```

이동 명령은 `actionId`와 `running` 또는 `completed` 상태를 반환합니다. 비동기 이동 완료는 `get_game_state`의 `isMoving`, `remainingDistance`, `lastActionStatus`로 확인합니다.

### 상호작용

먼저 `get_surroundings`가 반환한 `targetId`를 사용합니다.

```json
{
  "targetId": "instance:12345"
}
```

이름은 ID가 없을 때만 보조 경로로 사용합니다.

```json
{
  "targetName": "Terminal"
}
```

### 인게임 채팅

```json
{
  "message": "주변을 확인했습니다."
}
```

## 보안·실행 경계

- Listener는 숫자형 루프백 `127.0.0.1`에만 바인딩합니다.
- 실행할 때마다 새 토큰을 만들고 Inspector나 로그에 출력하지 않습니다.
- 요청 Body, 대기 시간, 프레임당 처리량을 제한합니다.
- Timeout 전에 시작하지 못한 요청은 큐에서 폐기합니다.
- 이미 실행을 시작한 비멱등 요청이 Timeout되면 완료 여부가 불명확하므로 자동 재호출하지 않습니다.
- 임의 C# 실행, 원격 Bind, 게임 파일 탐색은 제공하지 않습니다.
- 상호작용은 제한 반경과 명시적 인터페이스를 통과해야 합니다.
- 채팅 길이는 500자로 제한합니다.

## 현재 샘플 한계

- `HttpListener`를 지원하는 Desktop 실행 환경을 기준으로 합니다. WebGL은 Assembly Definition에서 제외합니다.
- 주변 탐색은 3D Physics 기준입니다.
- 이동은 `NavMeshAgent`나 `CharacterController`가 아닌 직접 Transform 이동입니다.
- `health`, `maxHealth`, `currentObjective`는 Inspector 샘플 값입니다.
- 게임별 Save, Inventory, Combat, Quest 규칙은 이 샘플에 포함하지 않습니다.
- 실제 제품에서는 각 명령을 게임의 권위 시스템과 연결하고, 재시도 가능한 상태 변경에는 idempotency key 또는 Action 결과 조회를 추가해야 합니다.
