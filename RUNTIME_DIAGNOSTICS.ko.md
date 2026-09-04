# 선택형 런타임 진단 계약

`GameRuntimeMcpHost`는 전송 계층. 범용 진단은 게임 소유 Adapter가 기존 Tool Manifest를 통해 선택적으로 노출하는 읽기 중심 관측 기능.

Unity 통합 샘플은 `GameRuntimeMcpBridge` 안에 이 기능을 포함. 별도 Listener·Session·Token·Provider Component 없음.

## Tool

| MCP Tool | Unity RPC | 역할 |
|---|---|---|
| `runtime_status` | `runtime.status` | Runtime·Process·Scene 상태 |
| `runtime_build_info` | `runtime.build_info` | Build·Version 식별 |
| `runtime_logs_read` | `runtime.logs.read` | 제한형 증분 Log |
| `runtime_metrics_snapshot` | `runtime.metrics.snapshot` | 단일 성능 Snapshot |
| `runtime_capture_screenshot` | `runtime.capture_screenshot` | 관리 경로의 화면 Capture |

진단 전용 Manifest 예시: [`examples/runtime-diagnostics.tools.json`](examples/runtime-diagnostics.tools.json)

통합 Unity Manifest: [`examples/unity/game-runtime.tools.json`](examples/unity/game-runtime.tools.json)

## 경계

- 읽기 중심 관측
- 게임 플레이 권한 없음
- 게임별 상태 Tool 대체 금지
- Runtime 임의 C# 실행 미포함
- Session Token 출력 금지
- 제한된 Log Ring Buffer
- 제한된 단일 Metrics Snapshot
- Adapter 관리 Screenshot 경로
- 호출자 임의 출력 경로 미허용

## `runtime.build_info`

권장 결과:

```json
{
  "product": "ExampleGame",
  "version": "0.1.0",
  "unityVersion": "6000.x",
  "buildId": "stable-build-id",
  "developmentBuild": true,
  "platform": "WindowsPlayer",
  "scriptingBackend": "IL2CPP",
  "sourceRevision": "optional",
  "processId": 1234
}
```

`sourceRevision`은 Unity 자동 제공 값이 아님. 프로젝트 Build Pipeline에서 주입하는 선택값.

## `runtime.logs.read`

권장 입력:

```json
{
  "sinceSequence": 42,
  "level": "error",
  "contains": "optional text",
  "limit": 50,
  "includeStackTrace": false
}
```

권장 결과:

```json
{
  "entries": [
    {
      "sequence": 43,
      "timestampUtc": "2026-09-04T00:00:00.0000000Z",
      "level": "error",
      "message": "bounded message",
      "stackTrace": ""
    }
  ],
  "oldestSequence": 1,
  "newestSequence": 60,
  "nextSequence": 43,
  "truncated": false,
  "hasMore": true,
  "cursorReset": false
}
```

Cursor 규칙:

```text
첫 호출: sinceSequence = 0
다음 호출: sinceSequence = 이전 nextSequence
반복 조건: hasMore == true
```

상태:

- `truncated`: 요청 Cursor보다 오래된 Log 제거
- `cursorReset`: 현재 Runtime보다 앞선 Cursor 감지
- `nextSequence`: 다음 호출에 전달할 Cursor
- `newestSequence`: 요청 처리 시점 최신 Sequence

필터로 제외된 항목도 검사된 범위까지 `nextSequence` 전진. 페이지 경계 뒤 미검사 항목 건너뛰기 금지.

## `runtime.metrics.snapshot`

현재 프레임의 저비용 Snapshot:

```text
Frame Count
Unscaled Delta Time
Smooth Delta Time
Approximate FPS
Managed Memory
Allocated / Reserved Memory
Mono Heap / Used
System / Graphics Memory
```

일반 게임 상태 조회에 사용하지 않음. 성능 질문과 전후 비교에만 사용.

## `runtime.capture_screenshot`

출력:

```text
Application.persistentDataPath
└─ GameRuntimeMcpDiagnostics
   └─ runtime_yyyyMMdd_HHmmss_fff.png
```

응답의 `queued = true`는 캡처 예약 완료. 파일 기록 완료와 동일 의미 아님.

## 권장 우선순위

```text
정확한 게임 소유 상태·행동 Tool
-> 필요한 범용 진단
-> 기능 미노출 보고
```

Screenshot·Log·Metrics를 권위 게임 상태의 대체 근거로 사용하지 않음.
