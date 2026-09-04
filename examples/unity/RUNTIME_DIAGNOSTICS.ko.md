# Unity 런타임 진단 Provider

[English](RUNTIME_DIAGNOSTICS.md)

`UnityRuntimeDiagnosticsProvider`는 빌드된 Player를 관측하기 위한 명시적 선택형 Component다.

두 번째 전송 경로를 시작하지 않고, 게임 소유 런타임 어댑터를 대체하지 않으며, 게임 플레이 명령도 포함하지 않는다.

## 제공 기능

- `ReadBuildInfo()` — 제품·버전·Build GUID·엔진·플랫폼·Backend·프로세스 식별
- `ReadLogs()` — Sequence Cursor를 사용하는 제한된 증분 Unity 로그
- `ReadMetricsSnapshot()` — 저비용 Frame·Memory 스냅샷 하나
- `CaptureScreenshot()` — `Application.persistentDataPath` 아래에 스크린샷 하나 예약

## 연결 구조

게임 소유 어댑터가 RPC Dispatch를 계속 담당한다. 선택형 진단 RPC 명령을 이 Provider에 연결한다.

```text
runtime.build_info
  -> diagnostics.ReadBuildInfo()

runtime.logs.read
  -> diagnostics.ReadLogs(request)

runtime.metrics.snapshot
  -> diagnostics.ReadMetricsSnapshot()

runtime.capture_screenshot
  -> diagnostics.CaptureScreenshot()
```

포함된 `UnityRuntimeMcpSampleBridge`는 활성화된 Provider가 같은 GameObject에 붙어 있거나 Inspector에 할당되어 있으면 이미 이 명령들을 연결한다.

진단용 Listener를 새로 만들지 않는다. 게임이 이미 사용하는 런타임 Adapter·Session·Token을 그대로 재사용한다.

## 로그 동작

`ReadLogs()`는 크기가 제한된 Ring Buffer를 사용한다.

- 이전 `nextSequence`를 다음 `sinceSequence`로 전달한다.
- `hasMore`가 true인 동안 다음 페이지를 읽는다.
- `limit`으로 각 결과 페이지 크기를 제한한다.
- 더 많은 데이터를 요청하기 전에 `level`·`contains` 필터를 사용한다.
- Stack Trace는 필요할 때만 요청한다.

Cursor 필드:

| 필드 | 의미 |
|---|---|
| `oldestSequence` | Ring Buffer에 남아 있는 가장 오래된 항목 |
| `newestSequence` | 호출 처리 시점에 캡처된 가장 최신 항목 |
| `nextSequence` | 다음 호출에 전달할 Cursor |
| `truncated` | 요청 Cursor보다 오래된 데이터가 이미 제거됨 |
| `hasMore` | 이 페이지 뒤 아직 검사하지 않은 항목이 남음 |
| `cursorReset` | 입력 Cursor가 현재 런타임보다 앞서 있어 보존 데이터부터 다시 읽음 |

필터에서 제외되었더라도 검사한 항목은 `nextSequence`를 전진시킨다. 페이지 경계 뒤 아직 검사하지 않은 항목은 건너뛰지 않는다. `cursorReset` 뒤에는 이전 프로세스의 로그라고 해석하기 전에 런타임·빌드 식별값을 다시 확인한다.

## 스크린샷 동작

호출자가 파일 경로를 선택하지 않는다. Provider는 `Application.persistentDataPath` 아래의 어댑터 관리 디렉터리에 파일명을 생성한다.

반환값은 캡처가 예약되었음을 뜻한다. 실제 이미지 파일은 현재 Frame 이후에 기록될 수 있다.

## Source Revision

Unity는 소스 제어 Revision을 자동으로 제공하지 않는다. 소스 일치 검증이 필요하면 프로젝트 빌드 Pipeline에서 Component의 선택형 `sourceRevision` 값을 설정한다.
