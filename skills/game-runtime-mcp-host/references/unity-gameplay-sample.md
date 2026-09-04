# Unity 게임 플레이 샘플 절차

다음 도구가 노출되어 있을 때 사용하는 낮은 추론량용 고정 절차다.

- `runtime_status`
- `get_game_state`
- `get_surroundings`
- `player_move_to`
- `player_interact`
- `send_in_game_chat`

## 상태 파악

1. `runtime_status`
2. `get_game_state`
3. 주변 대상이 필요할 때만 `get_surroundings`

현재 위치, 이동 중 여부, 목표, 주변 대상 ID를 확인한다.

## 이동

1. `get_game_state`에서 현재 위치와 `isMoving`을 확인한다.
2. `player_move_to`를 한 번 호출한다.
3. 반환된 `accepted`, `actionId`, `status`를 확인한다.
4. `accepted = false`면 같은 요청을 반복하지 않고 `code`와 `message`를 보고한다.
5. `status = running`이면 `get_game_state`를 다시 호출해 `isMoving`, `remainingDistance`, `lastActionStatus`를 확인한다.
6. `lastActionStatus = completed`가 되면 이동 검증을 종료한다.

Timeout이 발생했다면 같은 이동을 즉시 재호출하지 않는다. 먼저 `get_game_state`에서 위치와 최근 Action 상태를 확인한다.

## 주변 탐색

1. 필요한 최소 반경으로 `get_surroundings`를 호출한다.
2. 거리순 결과에서 목적에 맞는 대상을 고른다.
3. 상호작용할 대상은 `interactable = true`인지 확인한다.
4. 이름보다 `targetId`를 우선 보존한다.

반경이나 결과 수를 무조건 최댓값으로 요청하지 않는다.

## 상호작용

1. 직전에 읽은 주변 결과의 `targetId`를 사용한다.
2. `player_interact`를 한 번 호출한다.
3. `accepted`, `code`, `message`를 확인한다.
4. 게임별 권위 상태 도구가 있으면 상호작용 결과를 다시 조회한다.

`targetName`은 ID가 없을 때만 사용한다. 같은 이름의 대상이 여러 개일 수 있으므로 가능하면 다시 주변을 읽어 ID를 확보한다.

## 채팅

`send_in_game_chat`은 다른 게임 행동과 분리해서 호출한다.

- 빈 메시지를 보내지 않는다.
- 500자를 넘기지 않는다.
- 채팅 전달 성공을 이동·상호작용 성공으로 해석하지 않는다.

## 대표 호출 순서

```text
runtime_status
-> get_game_state
-> get_surroundings
-> player_move_to
-> get_game_state로 완료 확인
-> get_surroundings로 대상 재확인
-> player_interact
-> 게임별 상태로 최종 검증
```
