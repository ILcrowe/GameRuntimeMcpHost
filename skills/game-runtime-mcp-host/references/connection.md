# 런타임 연결

## 정상 연결

```text
Tool 노출 확인
-> 다중 Session이면 Instance·Role 선택
-> runtime_status
-> Product / Process / Scene 확인
-> 필요 시 runtime_build_info
-> 요청 작업
```

Host의 책임: 전송과 Session 선택.

게임 Adapter의 책임:

```text
허용 Command
권한
합법 행동
권위 상태 변경
```

## 다중 Session

같은 Product의 Runtime이 여러 개면 MCP Client 등록 단계에서 대상을 고정.

```text
--session-instance client-01
--session-role client
```

선택 우선순위:

1. `product`
2. `instanceId`
3. `role`
4. 일치 후보 중 최신 Descriptor

Descriptor에 `instanceId`가 없으면 `game-runtime-mcp-session-client-01.json` 같은 파일명 접미사로 Instance 선택 가능.

`role` 선택은 Descriptor의 `role` 필드 필요.

선택 뒤 `runtime_status`에서 Product·Process·Scene 재확인. 대상 불일치 시 상태 변경 중단.

## Session 없음

- 게임 플레이 상태 변경 중단
- 일치하는 Runtime Session 없음 보고
- Runtime의 Session Descriptor 게시 뒤 읽기 Tool 재호출
- `--session-name`·`--session-product` 자동 탐색 사용 시 다음 호출에서 재탐색
- Instance·Role 선택자 오타 확인

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
2. Instance ID·Role
3. Process ID·Session ID
4. Build GUID·Build ID
5. Source Revision·Version

다른 Product·Instance 또는 오래된 Build 확인 시 상태 변경 중단.
