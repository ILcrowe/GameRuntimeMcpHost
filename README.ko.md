# GameRuntimeMcpHost

[English README](README.md)

명시적으로 허용한 게임 런타임 명령을 MCP 호환 AI 클라이언트에 제공하는 의존성 없는 stdio Host.

```text
MCP Client
  -> stdio
  -> GameRuntimeMcpHost
  -> 127.0.0.1 HTTP RPC + 세션별 Token
  -> 게임 소유 Runtime Adapter
```

Host의 책임은 전송. 합법 행동 판정, 권한, 게임 규칙, 권위 상태 변경은 게임 소유 Adapter의 책임.

## 요구사항

- Python 3.10+
- MCP 호환 Client
- 세션 기술자 생성과 RPC 계약 처리가 가능한 게임 Runtime Adapter
- Host와 Runtime의 동일 PC 실행

## 설치

```powershell
git clone https://github.com/ILcrowe/GameRuntimeMcpHost.git
cd GameRuntimeMcpHost
python -m pip install -e .
```

검증:

```powershell
game-runtime-mcp-host --help
python -m unittest discover -s tests -v
```

## 빠른 시작

명시적 세션 파일:

```powershell
game-runtime-mcp-host `
  --session-file C:\path\to\runtime-session.json `
  --tools-file C:\path\to\tools.json
```

`LocalLow` 자동 탐색:

```powershell
game-runtime-mcp-host `
  --session-name game-runtime-mcp-session.json `
  --session-product UnityGameRuntime `
  --tools-file examples\unity\game-runtime.tools.json
```

Host 선실행 지원. Runtime 재시작 뒤 다음 Tool 호출에서 최신 세션 재탐색.

## Unity 통합 샘플

하나의 공통 Bridge에 범용 진단과 등록형 게임 명령을 결합한 샘플:

```text
examples/unity/
├─ Runtime/
│  ├─ GameRuntimeMcpBridge.cs
│  ├─ SampleGameRuntimeHandler.cs
│  └─ SampleRuntimeMcpInteractable.cs
├─ Tests/
│  └─ GameRuntimeMcpTests.cs
└─ game-runtime.tools.json
```

역할:

- `GameRuntimeMcpBridge`: 세션·Token·Loopback Listener·메인 스레드 Queue·Command Registry·범용 진단
- `SampleGameRuntimeHandler`: 상태·주변·이동·상호작용·채팅
- `SampleRuntimeMcpInteractable`: Inspector 부착형 상호작용 예제
- `game-runtime.tools.json`: MCP Tool Schema와 내부 RPC Command 매핑
- `GameRuntimeMcpTests`: 연결·진단·게임 행동 PlayMode 왕복

상세: [`examples/unity/README.ko.md`](examples/unity/README.ko.md)

## 범용 런타임 진단

| MCP Tool | 역할 |
|---|---|
| `runtime_status` | Runtime·Process·Scene 상태 |
| `runtime_build_info` | Build·Version·Platform·Backend 식별 |
| `runtime_logs_read` | 제한형 증분 Log |
| `runtime_metrics_snapshot` | 단일 성능 Snapshot |
| `runtime_capture_screenshot` | Adapter 관리 경로의 화면 Capture |

게임별 명령 대체 금지. Runtime 임의 C# 실행 미포함.

진단 계약: [`RUNTIME_DIAGNOSTICS.ko.md`](RUNTIME_DIAGNOSTICS.ko.md)

## 게임 플레이 Tool

| MCP Tool | Unity RPC |
|---|---|
| `get_game_state` | `game.get_state` |
| `get_surroundings` | `game.get_surroundings` |
| `player_move_to` | `player.move_to` |
| `player_interact` | `player.interact` |
| `send_in_game_chat` | `chat.send` |

확장 방식:

```text
기능군 Handler
-> GameRuntimeMcpBridge.Bind(...)
-> RegisterAll(owner, ...)
-> 게임 소유 서비스 호출
-> RuntimeCommandResult.Ok / Fail
-> OnDisable에서 UnregisterAll(owner)
```

## Agent Skill

낮은 추론량용 Skill:

```text
skills/game-runtime-mcp-host/
```

고정 순서:

```text
대상 판별
-> runtime_status
-> 필요 시 runtime_build_info
-> 정확한 게임 소유 Tool
-> 결과·상태 재조회
-> 필요한 진단만 추가
```

프로젝트 로컬 설치:

```powershell
& "C:\path\to\GameRuntimeMcpHost\skills\install-codex.ps1" `
  -TargetProject "C:\path\to\YourUnityProject"
```

설치 위치:

```text
<YourUnityProject>/.agents/skills/game-runtime-mcp-host/
```

MCP 등록은 호출 가능한 Tool 제공. Skill은 선택·재시도·검증 절차 제공.

## 외부 Agent Session Adapter

0.3 기능:

- `CodexPersistentSession`: Codex app-server 1개, Primary Thread 1개, 격리 Utility Thread
- `GrokHeadlessSession`: 구조화 출력과 Native `--resume`
- `JsonRpcStdioClient`
- `ProviderSessionDescriptor`
- `AppendOnlyConversationStream`

소비 게임의 책임:

```text
Prompt
JSON Schema
대화 규칙
권위 상태 변경
```

공용 모듈의 책임:

```text
Provider Process 전송
Native Session 연속성
```

상세: [`EXTERNAL_AGENT_SESSIONS.md`](EXTERNAL_AGENT_SESSIONS.md)

## MCP Client 설정

일반 stdio 등록:

```json
{
  "mcpServers": {
    "game_runtime": {
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
        "C:/path/to/GameRuntimeMcpHost/examples/unity/game-runtime.tools.json"
      ],
      "env": {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1"
      }
    }
  }
}
```

Codex 등록:

```powershell
codex mcp add game_runtime `
  --env PYTHONIOENCODING=utf-8 `
  --env PYTHONUTF8=1 `
  -- python -X utf8 C:\path\to\GameRuntimeMcpHost\src\game_runtime_mcp_host.py `
  --session-name game-runtime-mcp-session.json `
  --session-product UnityGameRuntime `
  --tools-file C:\path\to\GameRuntimeMcpHost\examples\unity\game-runtime.tools.json
```

등록·Skill 변경 뒤 새 Client Session.

## 세션 기술자

게임 소유 Adapter가 `Application.persistentDataPath` 등에 게시하는 계약:

```json
{
  "protocolVersion": 1,
  "endpoint": "http://127.0.0.1:18765/",
  "token": "per-session-secret",
  "tokenHeader": "X-Game-Runtime-Token",
  "rpcPath": "/rpc",
  "product": "UnityGameRuntime",
  "processId": 1234
}
```

제약:

- 숫자형 Loopback Endpoint
- 실행별 Token
- Token의 Log·MCP 응답 노출 금지

## Tool Manifest

| Manifest | 용도 |
|---|---|
| [`examples/tools.example.json`](examples/tools.example.json) | 최소 범용 계약 |
| [`examples/runtime-diagnostics.tools.json`](examples/runtime-diagnostics.tools.json) | 진단 전용 계약 예시 |
| [`examples/unity/game-runtime.tools.json`](examples/unity/game-runtime.tools.json) | Unity 통합 진단·게임 플레이 샘플 |
| [`examples/storyllmmaster.tools.json`](examples/storyllmmaster.tools.json) | 외부 게임 마스터 제어면 |
| [`examples/llm-conversation-runtime.tools.json`](examples/llm-conversation-runtime.tools.json) | 다중 참여자 대화 Runtime |

`clientName`은 관측 메타데이터. 권한 수단 아님.

## 환경 변수

| 환경 변수 | 명령행 옵션 |
|---|---|
| `GAME_RUNTIME_MCP_SESSION` | `--session-file` |
| `GAME_RUNTIME_MCP_SESSION_NAME` | `--session-name` |
| `GAME_RUNTIME_MCP_SESSION_PRODUCT` | `--session-product` |
| `GAME_RUNTIME_MCP_TOOLS` | `--tools-file` |
| `GAME_RUNTIME_GROK_SOURCE_HOME` | 격리 Grok Home용 인증 원본 |

명령행 값 우선.

## 문제 해결

| 증상 | 확인 |
|---|---|
| Tool 미노출 | Manifest JSON, Host 등록 경로, 새 Client Session |
| Runtime Session 없음 | 게임 실행, Session Name, Product, 명시적 Session File |
| Connection Refused | Runtime Listener, 최신 Descriptor Port |
| Endpoint 거부 | `127.0.0.1` 또는 `::1` |
| 인증 실패 | Runtime 재시작 여부, 읽기 Tool 재호출을 통한 최신 Token 재로딩 |
| 진단 비활성 | Bridge의 `Enable Diagnostics` |
| 한글 깨짐 | `python -X utf8`, `PYTHONIOENCODING=utf-8`, `PYTHONUTF8=1` |
| Grok 개인 설정 상속 | `GrokHeadlessSession`의 격리 `GROK_HOME` |

## 범위

포함:

```text
MCP initialize / ping / tools
Localhost RPC
Token 전달
Bounded Timeout
Session 재탐색
Unity 통합 샘플
범용 Runtime 진단
Provider Session 전송
```

제외:

```text
Runtime 임의 C# 실행
Remote Bind
게임 파일 접근
Provider SDK 직접 호출
게임별 Prompt
게임 규칙 검증
```

## A/B 테스트

동일 게임 요청 기준:

```text
낮은 추론량
vs
높은 추론량
```

비교 항목:

```text
Tool 선택
호출 수
존재하지 않는 Tool 생성
상태 변경 전 조회
상태 변경 후 재검증
Timeout 뒤 비멱등 재호출
최종 상태 일치
```

## 기여·보안

- 기여: [`CONTRIBUTING.md`](CONTRIBUTING.md)
- 보안: [`SECURITY.md`](SECURITY.md)
- License: MIT
