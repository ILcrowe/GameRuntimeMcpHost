# GameRuntimeMcpHost

[English README](README.md)

명시적으로 허용한 게임 런타임 명령을 모델 문맥 프로토콜(Model Context Protocol, MCP) 호환 AI 클라이언트에 제공하는 의존성 없는 stdio 호스트입니다.

```text
MCP 클라이언트
  -> stdio
  -> GameRuntimeMcpHost
  -> 127.0.0.1 RPC + 세션별 토큰
  -> 게임 소유 런타임 어댑터
```

호스트는 전송만 담당합니다. 합법 행동, 턴 검증, 권한 판정, 실제 상태 변경의 최종 권한은 게임 어댑터에 남습니다.

## 요구사항

- Python 3.10 이상
- MCP 호환 클라이언트
- 세션 기술자를 만들고 선언된 RPC 계약을 처리하는 게임 런타임 어댑터

런타임과 호스트는 같은 컴퓨터에서 실행해야 합니다.

## 설치

```powershell
git clone https://github.com/ILcrowe/GameRuntimeMcpHost.git
cd GameRuntimeMcpHost
python -m pip install -e .
```

설치를 확인합니다.

```powershell
game-runtime-mcp-host --help
python -m unittest discover -s tests -v
```

## 빠른 시작

런타임 어댑터를 먼저 실행한 뒤 세션 기술자와 도구 매니페스트를 전달합니다.

```powershell
game-runtime-mcp-host `
  --session-file C:\path\to\runtime-session.json `
  --tools-file C:\path\to\tools.json
```

`LocalLow` 아래에 세션을 만드는 런타임은 자동 탐색을 사용할 수 있습니다. 게임보다 호스트를 먼저 시작해도 유지되며, Play Mode나 프로세스를 재시작하면 다음 호출에서 새 세션을 찾습니다.

```powershell
game-runtime-mcp-host `
  --session-name llm-conversation-lab-runtime-mcp.json `
  --session-product LLMConversationLab `
  --tools-file examples/llm-conversation-runtime.tools.json
```

### Unity C# 어댑터 샘플

복사해서 사용할 수 있는 Unity 어댑터와 전용 매니페스트, 플레이 모드(PlayMode) 왕복 테스트를 포함합니다.

- [`examples/unity/README.ko.md`](examples/unity/README.ko.md) — 설정, 씬 배치, 확장, 보안 경계
- [`UnityRuntimeMcpSampleBridge.cs`](examples/unity/Runtime/UnityRuntimeMcpSampleBridge.cs) — 루프백 리스너, 세션 기술자, 제한된 메인 스레드 처리
- [`unity-runtime-sample.tools.json`](examples/unity/unity-runtime-sample.tools.json) — `runtime_status`, `echo_message`

샘플은 명시적 `MonoBehaviour`이며 숨은 런타임 부트스트랩을 설치하지 않습니다.

## 외부 Agent 세션 어댑터

0.3부터 로그인된 CLI를 사용하는 재사용 가능한 Provider 세션 어댑터도 제공합니다.

- `CodexPersistentSession` — Codex app-server 프로세스 하나, primary thread 하나, 격리된 utility thread
- `GrokHeadlessSession` — `grok -p`의 구조화 출력과 native `--resume`을 사용하는 제한 시간형 호출
- `JsonRpcStdioClient`, `ProviderSessionDescriptor`, `AppendOnlyConversationStream` — Provider 중립 프로세스·세션 기반 코드

게임은 여전히 프롬프트, JSON Schema, 대화 규칙, 권위 상태 변경을 소유합니다. 이 모듈들은 Provider 프로세스 전송과 native session 연속성만 담당합니다. 자세한 구조는 [`EXTERNAL_AGENT_SESSIONS.md`](EXTERNAL_AGENT_SESSIONS.md)를 확인합니다.

## MCP 클라이언트 설정

설정 파일 위치는 클라이언트마다 다르지만 stdio 등록 내용은 다음과 같습니다.

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
        "llm-conversation-lab-runtime-mcp.json",
        "--session-product",
        "LLMConversationLab",
        "--tools-file",
        "C:/path/to/GameRuntimeMcpHost/examples/llm-conversation-runtime.tools.json"
      ],
      "env": {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1"
      }
    }
  }
}
```

Codex CLI에서는 같은 프로세스를 다음처럼 등록합니다.

```powershell
codex mcp add game_runtime `
  --env PYTHONIOENCODING=utf-8 `
  --env PYTHONUTF8=1 `
  -- python -X utf8 C:\path\to\GameRuntimeMcpHost\src\game_runtime_mcp_host.py `
  --session-name llm-conversation-lab-runtime-mcp.json `
  --session-product LLMConversationLab `
  --tools-file C:\path\to\GameRuntimeMcpHost\examples\llm-conversation-runtime.tools.json
```

MCP 등록을 바꾼 뒤에는 클라이언트에서 새 세션을 엽니다.

## 세션 기술자

게임 소유 어댑터는 다음 계약의 JSON 파일을 만듭니다.

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

endpoint는 숫자형 루프백 주소여야 합니다. 토큰은 로그나 MCP 응답에 포함하지 않습니다.

## 도구 매니페스트

도구 매니페스트는 MCP 도구 이름을 게임 소유 RPC 명령 및 JSON 스키마와 연결합니다.

| 매니페스트 | 용도 |
|---|---|
| [`tools.example.json`](examples/tools.example.json) | 최소 범용 계약 |
| [`unity-runtime-sample.tools.json`](examples/unity/unity-runtime-sample.tools.json) | 복사형 Unity C# 어댑터 샘플 |
| [`storyllmmaster.tools.json`](examples/storyllmmaster.tools.json) | 외부 게임 마스터 제어면 |
| [`llm-conversation-runtime.tools.json`](examples/llm-conversation-runtime.tools.json) | 다중 참여자 대화 런타임 |

`clientName`은 관측 정보이며 권한 판정에 사용하지 않습니다. 대화 참여자 도구는 호스트가 보관하는 런타임 세션 토큰과 별도로 `join_conversation`이 발급한 참여자 토큰을 사용합니다.

## 환경변수

| 환경변수 | 대응 옵션 |
|---|---|
| `GAME_RUNTIME_MCP_SESSION` | `--session-file` |
| `GAME_RUNTIME_MCP_SESSION_NAME` | `--session-name` |
| `GAME_RUNTIME_MCP_SESSION_PRODUCT` | `--session-product` |
| `GAME_RUNTIME_MCP_TOOLS` | `--tools-file` |
| `GAME_RUNTIME_GROK_SOURCE_HOME` | 격리 런타임 홈으로 인증만 복사할 원본 Grok 홈 |

명령줄 값이 환경변수 기본값보다 우선합니다.

## 문제 해결

| 증상 | 확인할 항목 |
|---|---|
| 도구가 보이지 않음 | 매니페스트 JSON, 등록 명령 경로를 확인하고 MCP 클라이언트를 다시 시작합니다. |
| 런타임 세션을 찾지 못함 | 게임을 실행하고 `--session-name`, `--session-product`를 확인하거나 `--session-file`을 직접 지정합니다. |
| 연결 거부 | 런타임 어댑터의 수신 상태와 세션 기술자의 현재 포트를 확인합니다. |
| endpoint 거부 | `127.0.0.1` 또는 `::1` 같은 숫자형 루프백 주소를 사용합니다. 원격 주소는 의도적으로 차단됩니다. |
| 인증 실패 | 게임을 재시작하거나 다음 호출을 다시 시도해 최신 세션 토큰을 읽게 합니다. |
| 한글 깨짐 | Python에 `-X utf8`을 전달하고 `PYTHONIOENCODING=utf-8`, `PYTHONUTF8=1`을 설정합니다. |
| Grok가 개인 MCP 설정을 읽음 | `GrokHeadlessSession`은 scope별 `GROK_HOME`을 만들고 사용자 홈에서는 인증만 복사합니다. |

## 범위와 제한사항

- 포함: MCP 초기화, ping, 도구 조회·호출, localhost RPC, 토큰 전달, 제한된 타임아웃, 세션 재탐색, CLI 기반 외부 Agent 세션 전송
- 제외: 임의 C# 실행, 원격 bind, 게임 파일 접근, LLM 공급자 SDK 호출, 게임별 프롬프트 작성, 게임 규칙 검증
- 게임 어댑터 책임: 합법 행동 검증, 멱등성, 타임아웃 대체 경로, 권위 상태 변경, Save/Run scope 선택

## 기여와 보안

변경을 제안하기 전에 [CONTRIBUTING.md](CONTRIBUTING.md)를 확인합니다. 보안 문제는 [SECURITY.md](SECURITY.md)의 비공개 경로로 제보해 주세요.

## 라이선스

MIT — [LICENSE](LICENSE)를 확인하세요.
