# Unity 통합 샘플

대상 Tool Manifest:

```text
examples/unity/game-runtime.tools.json
```

## 연결

```text
runtime_status
-> Product / Process / Scene 확인
-> 필요 시 runtime_build_info
```

## 상태·이동·상호작용

```text
get_game_state
-> get_surroundings
-> player_move_to
-> get_game_state로 완료 확인
-> get_surroundings로 targetId 갱신
-> player_interact
-> 게임별 권위 상태 확인
```

## Tool별 기준

### `get_game_state`

- 위치
- 체력
- 목표
- 이동 상태
- 남은 거리
- Action ID·상태
- 최근 Chat

필요 필드만 사용.

### `get_surroundings`

- 필요한 최소 Radius
- 작은 `maxResults`
- 거리순 결과
- 상호작용은 `interactable == true`
- 이름보다 `targetId` 우선

### `player_move_to`

- 상태 조회 뒤 1회 호출
- `accepted` 확인
- `get_game_state`로 완료 확인
- 이동 중 반복 호출 금지

### `player_interact`

- 최신 주변 조회의 `targetId`
- 상호작용 반경 재확인
- `accepted`와 상태 재조회

### `send_in_game_chat`

- 다른 상태 변경과 분리
- 빈 문자열 금지
- 최대 500자
- 게임 소유 Chat 결과 확인

## 기능 미노출

Tool 이름이나 내부 RPC Command 생성 금지. 필요한 기능 미노출 보고.
