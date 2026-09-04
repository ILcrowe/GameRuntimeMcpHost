# 다중 Runtime 선택

같은 제품의 Player·Client·Server를 여러 개 실행할 때 Host가 대상 Session을 고정하는 방법.

## Session 검색

`--session-name`에 Wildcard가 없으면 Host는 두 패턴을 함께 검색한다.

```text
game-runtime-mcp-session.json
game-runtime-mcp-session-*.json
```

선택자가 없으면 기존 동작 유지:

```text
Product가 일치하는 후보
-> 가장 최근에 갱신된 Session Descriptor
```

## Instance 선택

Runtime Adapter가 Descriptor에 `instanceId`를 기록하는 방식:

```json
{
  "product": "ExampleGame",
  "instanceId": "client-01",
  "role": "client"
}
```

Host:

```powershell
game-runtime-mcp-host `
  --session-name game-runtime-mcp-session.json `
  --session-product ExampleGame `
  --session-instance client-01 `
  --session-role client `
  --tools-file C:\path\to\game-runtime.tools.json
```

환경 변수:

```text
GAME_RUNTIME_MCP_SESSION_INSTANCE
GAME_RUNTIME_MCP_SESSION_ROLE
```

## Unity 통합 샘플

현재 Unity Bridge의 공개 `SessionFileName`을 Instance별로 다르게 설정할 수 있다.

```csharp
bridge.SessionProductName = "ExampleGame";
bridge.SessionFileName =
    "game-runtime-mcp-session-client-01.json";
```

Host의 `--session-instance client-01`은 Descriptor에 `instanceId`가 없어도 파일명 접미사 `-client-01`을 식별한다.

`--session-role`은 Descriptor의 `role` 필드가 필요하다. 기본 Unity 샘플에서 Role이 필요하면 다음 중 하나 사용.

```text
1. Instance ID에 Role 포함
   client-01 / server-01

2. 게임 소유 Session Descriptor 확장에서 role 게시
```

## 권장 이름

```text
client-01
client-02
server-01
spectator-01
```

한 Runtime에 연결된 뒤 `runtime_status`로 Product·Process·Scene 재확인. 대상이 다르면 상태 변경 중단.
