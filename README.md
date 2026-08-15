# GameRuntimeMcpHost

게임 런타임의 제한된 localhost RPC를 Codex가 호출할 수 있도록 MCP stdio로
변환하는 독립 Host입니다.

```text
Codex
  -> MCP stdio
  -> GameRuntimeMcpHost
  -> 127.0.0.1 RPC + session token
  -> game-owned runtime adapter
```

이 저장소는 게임 규칙을 소유하지 않습니다. 유닛, 턴, legal action, 실제 상태
변경의 최종 권한은 각 게임 Adapter에 남습니다.

## 실행

Python 3.10 이상과 표준 라이브러리만 사용합니다.

```powershell
python src/game_runtime_mcp_host.py `
  --session-file path/to/runtime-session.json `
  --tools-file path/to/tools.json
```

LLMConversationLab은 세션 경로를 지정하지 않아도 기본적으로 최신 Lab 세션을 자동 감지합니다.
세션 경로를 자동 감지하는 Host는 게임보다 먼저 시작해도 종료되지 않습니다. 게임이 아직
꺼져 있으면 도구 호출만 연결 오류를 반환하고, 게임 시작 뒤 다음 호출에서 세션을 찾습니다.
Unity Play 재시작 뒤에도 다음 도구 호출 때 새 세션 파일·토큰을 다시 읽습니다.

```powershell
python src/game_runtime_mcp_host.py `
  --tools-file examples/llm-conversation-runtime.tools.json
```

환경변수도 사용할 수 있습니다.

- `GAME_RUNTIME_MCP_SESSION`
- `GAME_RUNTIME_MCP_TOOLS`

## Session contract

```json
{
  "protocolVersion": 1,
  "endpoint": "http://127.0.0.1:18761/",
  "token": "per-session-secret",
  "tokenHeader": "X-Game-Runtime-Token",
  "rpcPath": "/rpc",
  "product": "ExampleGame",
  "processId": 1234
}
```

Host는 endpoint가 loopback 주소가 아니면 연결을 거부합니다. 토큰은 로그나 MCP
응답에 포함하지 않습니다.

## Tool manifest

도구 이름과 게임 RPC command의 매핑은 게임이 소유한 manifest로 주입합니다.
[examples/tools.example.json](examples/tools.example.json)을 참고하세요.

외부 게임 마스터의 provider-neutral 예시는
[`examples/storyllmmaster.tools.json`](examples/storyllmmaster.tools.json)에 있습니다.
`clientName`은 관측 정보일 뿐 권한 판정에 사용하지 않으며 Codex, Claude Code,
그 밖의 MCP 호환 Agent가 같은 계약을 사용할 수 있습니다.

LLM·캐릭터 대화 런타임용 manifest는
[`examples/llm-conversation-runtime.tools.json`](examples/llm-conversation-runtime.tools.json)에 있습니다.
전역 Runtime 토큰과 별도로 `join_conversation`이 발급한 참여자 토큰을
`wait_turn`, `submit_action`, `read_events`, `leave_conversation`에 전달합니다.

## 경계

- 포함: MCP initialize/ping/tools, localhost RPC, token 전달, bounded timeout
- 제외: 임의 C# 실행, 원격 bind, 게임 파일 접근, 게임 규칙 검증
- 게임 Adapter 책임: legal action 생성·검증, idempotency, timeout fallback,
  authoritative state mutation

## 최초 실증

StoryLLMMaster Editor Play에서 Codex가 runtime status, controllable unit,
pending decision을 조회하고 `hold`를 제출해 authoritative turn `1 -> 2`를
확인한 구현에서 추출했습니다.
