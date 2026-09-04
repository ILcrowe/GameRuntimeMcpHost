# Unity 런타임 MCP 통합 샘플

[English guide](README.md)

실행 중인 Unity Player와 `GameRuntimeMcpHost`를 연결하고, 범용 진단과 게임 플레이 명령을 하나의 Bridge에서 제공하는 복사형 샘플.

원본 설계의 핵심 구조 유지: LLM Client → Python Host → 로컬 HTTP RPC → Unity 메인 스레드 → 게임 로직.

## 전체 구조

```text
MCP Client
  -> stdio JSON-RPC
  -> GameRuntimeMcpHost
  -> HTTP POST 127.0.0.1:{port}/rpc + Session Token
  -> GameRuntimeMcpBridge
     ├─ 시스템 명령과 범용 진단
     └─ 등록된 게임 명령
          -> SampleGameRuntimeHandler
```

## 파일 구성

```text
examples/unity/
├─ README.ko.md
├─ README.md
├─ game-runtime.tools.json
│
├─ Runtime/
│  ├─ GameRuntimeMcpBridge.cs
│  ├─ SampleGameRuntimeHandler.cs
│  ├─ SampleRuntimeMcpInteractable.cs
│  └─ lLCroweTool.GameRuntimeMcpHost.UnitySample.asmdef
│
└─ Tests/
   ├─ GameRuntimeMcpTests.cs
   └─ lLCroweTool.GameRuntimeMcpHost.UnitySample.Tests.asmdef
```

### 역할

| 파일 | 역할 |
|---|---|
| `GameRuntimeMcpBridge.cs` | 세션·토큰·Loopback Listener·메인 스레드 큐·명령 Registry·범용 진단 |
| `SampleGameRuntimeHandler.cs` | 게임 상태·주변 조회·이동·상호작용·채팅 |
| `SampleRuntimeMcpInteractable.cs` | Inspector에서 바로 붙이는 최소 상호작용 샘플 |
| `game-runtime.tools.json` | MCP Tool 이름·입력 Schema·Unity RPC 명령 매핑 |
| `GameRuntimeMcpTests.cs` | 연결·진단·게임 행동 PlayMode 왕복 검증 |

`SampleRuntimeMcpInteractable`만 별도 파일 유지. Unity Inspector에서 붙일 수 있는 `MonoBehaviour`는 파일 이름과 클래스 이름 일치가 필요한 구조이기 때문.

## Scene 구성

```text
Boot Scene
├─ RuntimeServices
│  └─ GameRuntimeMcpBridge
│
├─ ControlledEntity
│  └─ SampleGameRuntimeHandler
│
└─ Interactable
   ├─ Collider
   └─ SampleRuntimeMcpInteractable
```

### Bridge Inspector

```text
런타임 MCP
├─ Runtime MCP Enabled
├─ Persist Across Scenes
├─ Session Product Name
├─ Session File Name
├─ Preferred Port
├─ Port Search Count
└─ RPC Path

요청 제한
├─ Max Request Bytes
├─ Request Timeout Seconds
└─ Max Requests Per Frame

범용 진단
├─ Enable Diagnostics
├─ Log Capacity
├─ Message / Stack Trace 제한
├─ Diagnostics Folder Name
└─ Source Revision
```

## 제공 Tool

### 시스템·진단

| MCP Tool | Unity RPC | 역할 |
|---|---|---|
| `runtime_status` | `runtime.status` | Player·프로세스·씬·Pause 상태 |
| `runtime_build_info` | `runtime.build_info` | 제품·버전·Build GUID·Platform·Backend |
| `runtime_logs_read` | `runtime.logs.read` | Sequence Cursor 기반 제한형 로그 |
| `runtime_metrics_snapshot` | `runtime.metrics.snapshot` | 현재 프레임·메모리 스냅샷 |
| `runtime_capture_screenshot` | `runtime.capture_screenshot` | 관리 경로의 화면 캡처 예약 |

### 게임 플레이

| MCP Tool | Unity RPC | 역할 |
|---|---|---|
| `get_game_state` | `game.get_state` | 위치·체력·목표·이동·최근 행동 |
| `get_surroundings` | `game.get_surroundings` | 주변 객체와 상호작용 대상 |
| `player_move_to` | `player.move_to` | 제한 거리 안의 X/Z 이동 |
| `player_interact` | `player.interact` | `targetId` 우선 상호작용 |
| `send_in_game_chat` | `chat.send` | 게임 소유 채팅 이벤트 전달 |

첨부안의 다섯 게임 Tool 유지.

## 설치

1. `examples/unity/Runtime`을 Unity 프로젝트의 `Assets/GameRuntimeMcp/Runtime`으로 복사
2. 선택적으로 `examples/unity/Tests` 복사
3. `RuntimeServices`에 `GameRuntimeMcpBridge` 추가
4. 제어 대상에 `SampleGameRuntimeHandler` 추가
5. `Controlled Entity` 연결
6. 상호작용 대상에 Collider와 `SampleRuntimeMcpInteractable` 추가
7. Host 설치

```powershell
python -m pip install -e .
```

## Host 실행

```powershell
game-runtime-mcp-host `
  --session-name game-runtime-mcp-session.json `
  --session-product UnityGameRuntime `
  --tools-file C:\path\to\GameRuntimeMcpHost\examples\unity\game-runtime.tools.json
```

Unity Play Mode 또는 Desktop Player 시작 시 `Application.persistentDataPath`에 세션 기술자 생성. Host를 먼저 실행한 경우 다음 Tool 호출에서 최신 세션 자동 탐색.

## Codex MCP 등록

```powershell
codex mcp add unity_game_runtime `
  --env PYTHONIOENCODING=utf-8 `
  --env PYTHONUTF8=1 `
  -- python -X utf8 C:\path\to\GameRuntimeMcpHost\src\game_runtime_mcp_host.py `
  --session-name game-runtime-mcp-session.json `
  --session-product UnityGameRuntime `
  --tools-file C:\path\to\GameRuntimeMcpHost\examples\unity\game-runtime.tools.json
```

MCP 등록 변경 뒤 새 Codex 세션.

## Skill 설치

```powershell
& "C:\path\to\GameRuntimeMcpHost\skills\install-codex.ps1" `
  -TargetProject "C:\path\to\YourUnityProject"
```

설치 위치:

```text
<YourUnityProject>/.agents/skills/game-runtime-mcp-host/
```

## 게임 명령 추가

기능군 Handler 하나에 관련 명령 묶음 배치.

```csharp
private GameRuntimeMcpBridge.CommandBinding[] bindingList;

private void Awake()
{
    bindingList = new[]
    {
        GameRuntimeMcpBridge.Bind(
            "inventory.get_state",
            HandleGetInventory),
        GameRuntimeMcpBridge.Bind(
            "inventory.use_item",
            HandleUseItem)
    };
}

private void TryRegister()
{
    bridge.RegisterAll(
        this,
        out string error,
        bindingList);
}

private void OnDisable()
{
    bridge.UnregisterAll(this);
}
```

결과 생성:

```csharp
return GameRuntimeMcpBridge.RuntimeCommandResult.Ok(
    new InventoryResult
    {
        // 필요한 필드만 반환
    });
```

실패:

```csharp
return GameRuntimeMcpBridge.RuntimeCommandResult.Fail(
    "inventory_unavailable",
    "인벤토리를 사용할 수 없습니다.");
```

### Handler 분리 기준

| 상황 | 구성 |
|---|---|
| 명령 5~10개, 의존성·수명주기 동일 | 한 Handler 유지 |
| Inventory·Combat 등 서비스와 활성 시점 분리 | 기능군 Handler 분리 |
| Client·Server 권한 분리 | 권한 경계별 Handler 분리 |
| 파일 길이만 증가 | 분리 사유 아님 |

## 낮은 추론량 호출 순서

```text
runtime_status
-> 필요 시 runtime_build_info
-> get_game_state
-> get_surroundings
-> player_move_to
-> get_game_state로 이동 완료 확인
-> get_surroundings로 대상 갱신
-> player_interact
-> 게임별 권위 상태 확인
```

채팅은 별도 행동으로 `send_in_game_chat` 호출.

## 로그 Cursor

```text
runtime_logs_read(sinceSequence = 0)
-> entries 처리
-> nextSequence 보존
-> hasMore == true면 다음 페이지
-> 이후 새 로그는 보존한 nextSequence부터 조회
```

- `truncated`: Ring Buffer에서 과거 항목 제거
- `cursorReset`: 다른 프로세스·세션의 미래 Cursor 감지
- Stack Trace: 필요한 경우에만 `includeStackTrace = true`

## 보안·실행 경계

- 숫자형 Loopback `127.0.0.1` 전용
- 실행별 비공개 Session Token
- 요청 Body·Timeout·프레임당 처리량 제한
- 상태 변경 전 Main Thread 이동
- 시작 전 Timeout과 실행 여부 불명 Timeout 구분
- `Thread.Abort` 미사용
- Runtime C# Eval 미제공
- 원격 Bind·게임 파일 탐색 미제공
- 호출자 임의 Screenshot 경로 미허용
- 게임 합법 행동과 권위 상태 변경은 게임 Handler 소유

## 테스트

### 정적 계약 테스트

```powershell
python -m unittest discover -s tests -v
```

### Unity PlayMode

```text
GameRuntimeMcpTests.RuntimeToolsRoundTripThroughOneBridge
```

검증 범위:

```text
Token 인증
+ Runtime Status
+ Build Identity
+ 증분 Log
+ Metrics
+ Screenshot Queue
+ Game State
+ Surroundings
+ Move
+ Interact
+ Chat
+ Session 정리
```

## A/B 테스트

동일 요청을 낮은 추론량과 높은 추론량에서 실행한 뒤 다음 항목 비교.

```text
Tool 선택 정확도
호출 수
잘못된 Tool 이름 생성 여부
상태 변경 전 조회 여부
상태 변경 후 재검증 여부
Timeout 뒤 비멱등 재호출 여부
최종 상태 일치 여부
```

권장 요청:

```text
현재 게임 상태 확인
가장 가까운 상호작용 가능 대상 탐색
대상 근처로 이동
이동 완료 확인
대상 재탐색
상호작용
결과 확인
```

## 샘플 한계

- 3D `Physics.OverlapSphere`
- 직접 `Transform` 이동
- Inspector 기반 샘플 체력·목표
- 샘플 상호작용 Component
- Save·Inventory·Combat·Quest 규칙 미포함

상용 적용 시 프로젝트의 이동·상호작용·채팅·게임 상태 서비스로 Handler 내부 구현 교체.
