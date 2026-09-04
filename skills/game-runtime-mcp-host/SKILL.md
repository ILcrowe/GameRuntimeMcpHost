---
name: game-runtime-mcp-host
description: GameRuntimeMcpHost를 통해 실행 중인 빌드 Player를 제어·디버깅·검증할 때 사용한다. 명시적인 게임 소유 MCP 도구를 우선하고, 범용 런타임 진단은 관측에만 사용한다. Unity Editor의 Scene, Prefab, Asset, 제작 작업에는 사용하지 않는다.
---

# Game Runtime MCP Host

실행 중인 게임 Player가 GameRuntimeMcpHost에 연결된 작업에서 이 스킬을 사용한다.

이 스킬은 **낮은 추론량**에서도 안정적으로 동작하도록 작성되었다. 새로운 절차를 만들지 말고 아래 라우팅과 호출 순서를 그대로 따른다.

## 대상 판별

1. 대상이 빌드되어 실행 중인 게임 Player라면 이 스킬을 계속 사용한다.
2. 대상이 Unity Editor, Scene Asset, Prefab, Material, UI Document, Importer 또는 Editor 전용 상태라면 이 스킬 사용을 중단하고 Editor 도구 체계를 사용한다.
3. 명시적인 게임 플레이 명령이 존재하면 범용 런타임 진단으로 대신하지 않는다.

## 도구 선택 순서

아래에서 처음으로 적용되는 항목을 선택한다.

1. 요청한 상태나 행동에 정확히 대응하는 게임 소유 도구
2. 상태, 빌드 식별, 로그, 메트릭, 스크린샷 같은 정확한 범용 런타임 읽기 도구
3. 명시적으로 노출된 더 넓은 게임 소유 읽기·조회 도구
4. 필요한 기능이 노출되지 않았다고 보고한다. 도구 이름, RPC 명령, 숨은 필드, 게임 규칙을 지어내지 않는다.

## 필수 연결 절차

런타임 작업을 시작할 때 다음 순서를 따른다.

1. 실제로 노출된 도구 목록을 사용한다. 명령 이름을 추측하지 않는다.
2. `runtime_status`가 노출되어 있으면 호출한다.
3. 연결된 제품·프로세스·런타임이 목표 대상인지 확인한다.
4. 현재 빌드가 중요한 작업이고 `runtime_build_info`가 노출되어 있으면 호출한다.
5. 그다음에만 게임 플레이 또는 상태 변경 도구를 호출한다.

런타임이 없거나, 재시작되었거나, 인증 실패·오래된 세션·버전 불일치가 발생하면 [references/connection.md](references/connection.md)를 따른다.

## 필수 행동 루프

상태를 변경하는 게임 플레이 도구에는 다음 순서를 적용한다.

1. 관련된 최소 상태를 읽는다.
2. 상태 변경 행동 하나를 수행한다.
3. 결과 도구가 있으면 행동 결과를 읽는다.
4. 관련된 최소 상태를 다시 읽는다.
5. 로그, 메트릭, 스크린샷은 추가 증거가 될 때만 사용한다.

노출된 게임 도구가 하나의 원자적 묶음으로 정의한 경우가 아니면 서로 관련 없는 변경을 한 번에 묶지 않는다.

재시도와 권한 규칙은 [references/gameplay-control.md](references/gameplay-control.md)를 따른다.

## Unity 게임 플레이 샘플

다음 도구가 함께 노출되어 있으면 저장소의 등록형 게임 플레이 샘플 계약으로 취급한다.

- `get_game_state`
- `get_surroundings`
- `player_move_to`
- `player_interact`
- `send_in_game_chat`

고정 호출 순서와 이동·상호작용 검증 방식은 [references/unity-gameplay-sample.md](references/unity-gameplay-sample.md)를 따른다.

## 범용 진단

범용 진단은 관측 도구이며 게임 권한을 가지지 않는다.

어댑터가 노출한 경우 사용할 수 있는 권장 이름은 다음과 같다.

- `runtime_status`
- `runtime_build_info`
- `runtime_logs_read`
- `runtime_metrics_snapshot`
- `runtime_capture_screenshot`

사용 전 [references/diagnostics.md](references/diagnostics.md)를 따른다.

## 검증

도구 호출 성공만으로 게임 결과가 증명되었다고 판단하지 않는다. 요청에 중요한 상태를 다시 확인한다.

고정 검증 순서는 [references/verification.md](references/verification.md)를 따른다.

## 금지 규칙

- 런타임 세션 토큰을 출력·요청·저장·노출하지 않는다.
- 타임아웃이 발생한 비멱등 행동이 실패했다고 단정하지 않는다.
- 타임아웃 뒤 비멱등 행동을 무조건 재호출하지 않는다.
- 런타임 전송 경로로 게임 파일을 수정하지 않는다.
- 숨은 합법 행동을 추론하거나 게임 소유 검증을 우회하지 않는다.
- 권위 있는 게임 상태 도구가 있을 때 스크린샷·로그·메트릭을 게임 상태의 최종 근거로 사용하지 않는다.
