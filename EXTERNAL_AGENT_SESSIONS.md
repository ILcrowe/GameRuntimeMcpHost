# External Agent Session Adapters

[한국어](#한국어) · [English](#english)

## 한국어

GameRuntimeMcpHost 0.3부터 게임 런타임 RPC 전송 계층과 함께 **CLI 기반 외부 Agent 세션 어댑터**를 제공합니다.

```text
게임별 Prompt / JSON Schema / 권위 검증
                    ↓
GameRuntimeMcpHost Provider Session
├─ CodexPersistentSession
└─ GrokHeadlessSession
                    ↓
로그인된 Provider CLI
```

### 책임 경계

| 계층 | 책임 |
|---|---|
| 게임/대화 런타임 | 프롬프트 작성, JSON Schema 선택, 턴·권위·상태 변경 검증 |
| GameRuntimeMcpHost | Provider 프로세스 호출, 세션 ID 저장·복원, utility 대화 격리, 타임아웃·전송 진단 |
| Provider CLI | 실제 모델 호출과 Provider 고유 대화 저장소 |

StoryLLMMaster 같은 소비자는 시나리오·NPC·대화 규칙을 이 저장소에 넣지 않습니다. 이 저장소에는 재사용 가능한 Provider 연결 코드만 둡니다.

### Codex

`CodexPersistentSession`은 `codex app-server --listen stdio://` 프로세스 하나와 primary thread 하나를 유지합니다. 진단·행동 해석 같은 utility 요청은 별도 thread를 사용합니다.

```python
from pathlib import Path
from game_runtime_codex_session import CodexPersistentSession

session = CodexPersistentSession(Path("state/codex"))
result = session.generate(
    prompt,
    output_schema=schema,
    model="gpt-5.6-sol",
    reasoning_effort="low",
)
```

### Grok Build

`GrokHeadlessSession`은 직접 ACP lifecycle을 재구현하지 않습니다. Grok Build가 지원하는 headless 계약을 사용합니다.

```text
grok -p <prompt>
  --output-format json
  --json-schema <schema>
  --resume <sessionId>
```

각 요청은 bounded subprocess로 실행되고, 응답의 `sessionId`가 `provider_sessions.json`에 저장됩니다. 다음 primary 요청은 같은 ID를 `--resume`으로 이어갑니다. utility 채널은 primary session ID를 덮어쓰지 않습니다.

```python
from pathlib import Path
from game_runtime_grok_session import GrokHeadlessSession

session = GrokHeadlessSession(Path("state/grok"))
result = session.generate(prompt, output_schema=schema)
```

Grok child는 save/run 전용 `GROK_HOME`을 사용합니다. 사용자 홈에서는 `auth.json`만 복사하며 개인 MCP, 플러그인, 메모리 설정은 상속하지 않습니다.

### 저장 구조

```text
state-root/
├─ provider_sessions.json
├─ memory-stream/external-gm.jsonl
├─ codex-workspace/            # Codex 사용 시
├─ grok-workspace/             # Grok 사용 시
└─ grok-runtime-home/          # Grok 인증/세션 격리
```

`provider_sessions.json`은 Provider native session/thread ID만 저장합니다. 게임의 Save Slot·Run ID 경로 결정은 소비자가 담당합니다.

---

## English

GameRuntimeMcpHost 0.3 adds reusable **CLI-backed external-agent session adapters** beside the existing game-runtime RPC transport.

The game remains responsible for prompt construction, JSON Schemas, turn validation, and authoritative state changes. This repository owns provider process transport, native session ID persistence, utility-channel isolation, timeouts, and diagnostics.

- `CodexPersistentSession` keeps one Codex app-server process and one primary thread.
- `GrokHeadlessSession` uses Grok Build's supported `-p --output-format json --json-schema --resume` flow instead of reimplementing its ACP lifecycle.
- Provider-native IDs are stored in `provider_sessions.json`.
- Grok runs under an isolated per-scope `GROK_HOME`; only cached authentication is copied from the user's normal Grok home.

The adapters do not contain game-specific prompts, scenario data, or authority rules.
