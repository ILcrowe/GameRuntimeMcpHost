# 게임 플레이 제어

`GameRuntimeMcpHost`는 전송 계층. 게임 소유 Adapter가 합법 행동과 권위 상태 변경의 최종 결정권 보유.

## 낮은 추론량 행동 순서

```text
정확한 Tool 선택
-> 최소 문맥 조회
-> 행동 1개
-> Action Result
-> 영향 상태 재조회
-> 목표 상태 확인
```

이 순서로 충분한 경우 관련 없는 Tool 탐색 금지.

## 권한

```text
Model = 행동 제안
Game Adapter = 합법성 판정
Game Service = 권위 상태 변경
```

거절 행동을 범용 진단이나 더 낮은 수준의 명령으로 우회 금지.

## 재시도

### 읽기 전용

유효 응답이 없었던 것이 명확한 경우 재연결 뒤 재호출 가능.

### 멱등 상태 변경

Tool 계약의 멱등성 명시 또는 Idempotency·Action Key 존재 시에만 재시도.

### 비멱등 상태 변경

Timeout·Connection Loss 뒤:

```text
즉시 재제출 금지
-> 기존 Action ID 결과 조회
-> 권위 상태 재조회
-> 미실행 근거 확인
-> 계약이 허용한 경우만 재시도
```

## 이동

```text
get_game_state
-> player_move_to 1회
-> get_game_state 반복
-> isMoving == false
-> lastActionStatus 확인
```

이동 중 동일 명령 반복 금지.

## 상호작용

```text
get_surroundings
-> interactable == true
-> targetId 보존
-> 필요 시 이동
-> 주변 재조회
-> player_interact(targetId)
-> 결과·상태 확인
```

`targetName`은 ID가 없는 경우의 보조 경로.

## 턴·의사결정

노출된 경우:

```text
대기 의사결정
-> 문맥
-> 행동 제출
-> 행동 결과
-> 갱신 상태
```

Runtime 재연결·Turn Revision 변경 뒤 오래된 문맥 사용 금지.
