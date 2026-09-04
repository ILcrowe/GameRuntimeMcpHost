# 런타임 연결

## 정상 연결

```text
Tool 노출 확인
-> runtime_status
-> Product / Process / Scene 확인
-> 필요 시 runtime_build_info
-> 요청 작업
```

Host의 책임: 전송.

게임 Adapter의 책임:

```text
허용 Command
권한
합법 행동
권위 상태 변경
```

## Session 없음

- 게임 플레이 상태 변경 중단
- 일치하는 Runtime Session 없음 보고
- Runtime의 Session Descriptor 게시 뒤 읽기 Tool 재호출
- `--session-name`·`--session-product` 자동 탐색 사용 시 다음 호출에서 재탐색

## Connection Refused·오래된 Endpoint

- 행동 실행 여부 추측 금지
- Session 재탐색
- 읽기 전용 `runtime_status` 재호출
- 새 Runtime 정상 응답 뒤 작업 재개

## 인증 실패

Runtime 재시작 시 Session Token 교체 가능.

```text
Token 요청·출력 금지
-> 읽기 전용 상태 호출
-> Host의 최신 Descriptor 재로딩
-> 계속 실패 시 상태 변경 중단
```

## Protocol 불일치

- 반복 재연결 금지
- 상태 변경 중단
- 기대·실제 Protocol Version 보고
- Host·Adapter 호환성 문제로 분류

## 작업 중 Runtime 재시작

```text
runtime_status 재확인
-> 필요 시 runtime_build_info
-> 이전 Process·Session 가정 폐기
-> 최소 상태 재조회
-> 다음 행동
```

## 대상 식별 우선순위

1. Product·Runtime 이름
2. Process ID·Session ID
3. Build GUID·Build ID
4. Source Revision·Version

다른 Product 또는 오래된 Build 확인 시 상태 변경 중단.
