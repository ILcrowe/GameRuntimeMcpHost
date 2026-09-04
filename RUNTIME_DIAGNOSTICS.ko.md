# 선택형 런타임 진단 계약

[English](RUNTIME_DIAGNOSTICS.md)

GameRuntimeMcpHost는 전송 계층으로 유지된다. 이 문서는 게임 소유 어댑터가 기존 도구 매니페스트를 통해 선택적으로 노출할 수 있는 게임 독립 런타임 진단 계약을 정의한다.

CLI 계층은 필요하지 않다. GameRuntimeMcpHost가 연결된 Player 어댑터로 전달하는 일반 MCP 도구다.

## 목적

게임 플레이 명령은 명시적이며 게임이 소유해야 한다. 다만 일회성 게임 명령을 계속 추가하지 않고도 연결 상태, 빌드 최신성, 로그, 성능, 화면 결과를 확인할 수 있는 작은 공통 진단 표면은 유용하다.

권장 선택형 도구:

| MCP 도구 | RPC 명령 | 목적 |
|---|---|---|
| `runtime_status` | `runtime.status` | 런타임·프로세스 생존 및 식별 |
| `runtime_build_info` | `runtime.build_info` | 빌드·버전 식별 |
| `runtime_logs_read` | `runtime.logs.read` | 제한된 증분 로그 읽기 |
| `runtime_metrics_snapshot` | `runtime.metrics.snapshot` | 제한된 런타임 성능 스냅샷 |
| `runtime_capture_screenshot` | `runtime.capture_screenshot` | 시각 검증용 단일 캡처 |

범용 계약 매니페스트는 [`examples/runtime-diagnostics.tools.json`](examples/runtime-diagnostics.tools.json)에 있다. 복사형 Unity 샘플은 같은 진단을 [`examples/unity/unity-runtime-sample.tools.json`](examples/unity/unity-runtime-sample.tools.json)에 게시한다.

런타임 어댑터는 해당 MCP 도구를 게시하기 전에 대응 RPC 명령을 구현해야 한다.

## 경계

- 진단은 대부분 읽기 전용 관측 도구다.
- 게임 플레이 권한은 게임별 명령에 남는다.
- 런타임 임의 코드 실행은 기본 계약에 포함하지 않는다.
- 진단 결과에 세션 토큰을 포함하지 않는다.
- 로그는 크기가 제한되고 증분 읽기가 가능해야 한다.
- 스크린샷은 더 엄격한 게임별 계약이 없는 한 어댑터가 관리하는 진단 디렉터리만 사용한다.
- 메트릭은 무제한 스트리밍이 아니라 제한된 스냅샷이다.

## 권장 결과 계약

### `runtime.build_info`

```json
{
  "product": "ExampleGame",
  "version": "0.1.0",
  "engineVersion": "6000.x",
  "buildId": "stable-build-id",
  "developmentBuild": true,
  "platform": "WindowsPlayer",
  "scriptingBackend": "IL2CPP",
  "sourceRevision": "optional",
  "processId": 1234
}
```

### `runtime.logs.read`

```json
{
  "entries": [
    {
      "sequence": 42,
      "timestampUtc": "2026-09-04T00:00:00.0000000Z",
      "level": "error",
      "message": "bounded message",
      "stackTrace": ""
    }
  ],
  "oldestSequence": 1,
  "newestSequence": 48,
  "nextSequence": 42,
  "truncated": false,
  "hasMore": true,
  "cursorReset": false
}
```

Ring Buffer 크기와 메시지 제한은 어댑터가 소유한다.

- 이전 응답의 `nextSequence`를 다음 요청의 `sinceSequence`로 전달한다.
- `hasMore`가 true인 동안 다음 페이지를 읽는다.
- `truncated`는 요청 Cursor가 현재 보존 중인 가장 오래된 항목보다 이전임을 뜻한다.
- `cursorReset`은 보통 프로세스·세션 변경 뒤 입력 Cursor가 현재 Sequence보다 앞서 있어, 어댑터가 현재 보존 구간부터 다시 읽기 시작했음을 뜻한다.
- 필터에서 제외된 항목도 검사했다면 `nextSequence`를 전진시킬 수 있지만, 페이지 제한 뒤 아직 검사하지 않은 항목을 건너뛰면 안 된다.

### `runtime.metrics.snapshot`

어댑터가 저비용으로 일관되게 수집할 수 있는 지표만 반환한다. 전후 비교가 가능하도록 Schema를 안정적으로 유지한다.

### `runtime.capture_screenshot`

메타데이터와 생성된 파일 경로를 반환한다. 기본 계약에서는 큰 Base64 이미지를 Tool 결과로 보내지 않으며, 호출자가 임의 출력 경로를 지정하지 못하게 한다.

## Unity Provider

[`UnityRuntimeDiagnosticsProvider`](examples/unity/Runtime/UnityRuntimeDiagnosticsProvider.cs)는 빌드 식별, 제한된 로그, 메트릭 스냅샷, 어댑터 관리 스크린샷 경로를 구현한다. Unity 샘플 Bridge는 하나의 Listener·Session·Token을 유지한 채 대응 RPC 명령을 이 선택형 Component로 위임한다.

## 스킬 라우팅

저장소는 [`skills/game-runtime-mcp-host/`](skills/game-runtime-mcp-host/) 아래에 낮은 추론량용 스킬을 포함한다.

고정 순서는 다음과 같다.

`대상 판별 -> 런타임 상태 -> 빌드 식별 -> 정확한 게임 도구 -> 결과·상태 검증 -> 선택형 진단`
