---
name: game-runtime-mcp-host
description: GameRuntimeMcpHost를 통해 실행 중인 빌드 Player를 제어·디버깅·검증할 때 사용한다. 정확한 게임 소유 Tool 우선, 범용 진단은 보조 관측, Unity Editor 작업은 제외한다.
---

# Game Runtime MCP Host

실행 중인 게임 Player가 `GameRuntimeMcpHost`에 연결된 작업용 Skill.

낮은 추론량 기준의 고정 라우팅과 호출 순서. 새로운 Tool 이름·게임 규칙·복구 절차 생성 금지.

## 대상 판별

1. 빌드 또는 Play Mode의 실행 중 게임 상태·행동 → 이 Skill
2. Unity Editor Scene·Prefab·Asset·Importer·제작 작업 → Editor Tool 체계
3. C#·설정·Manifest 파일 수정 → Repository/File Tool
4. 명시적 게임 Tool 존재 → 범용 진단으로 우회 금지

## 도구 선택 순서

1. 요청과 정확히 일치하는 게임 소유 Tool
2. 정확한 범용 읽기 Tool
3. 명시적으로 노출된 더 넓은 게임 조회 Tool
4. 기능 미노출 보고

금지:

```text
Tool 이름 추측
RPC Command 직접 추측
숨은 Field 추측
게임 규칙 우회
Runtime C# Eval 대체
```

## 연결 순서

```text
노출 Tool 목록 확인
-> runtime_status
-> 대상 Product / Process / Scene 확인
-> 필요 시 runtime_build_info
-> 게임 상태 조회
-> 행동
```

연결 없음·재시작·인증 실패·Protocol 불일치: [references/connection.md](references/connection.md)

## 행동 순서

```text
관련 최소 상태 조회
-> 행동 1개
-> Action Result
-> 영향받은 최소 상태 재조회
-> 요청 상태 일치 확인
```

서로 관련 없는 상태 변경 묶음 금지. 게임 Tool이 하나의 원자 명령으로 정의한 경우만 예외.

재시도·권한: [references/gameplay-control.md](references/gameplay-control.md)

## Unity 통합 샘플

통합 Tool이 노출된 경우의 기본 순서:

```text
runtime_status
-> 필요 시 runtime_build_info
-> get_game_state
-> get_surroundings
-> player_move_to
-> get_game_state로 이동 완료 확인
-> get_surroundings로 대상 갱신
-> player_interact
-> 게임별 권위 상태 확인
```

채팅은 별도 행동:

```text
send_in_game_chat
-> 채팅 결과 또는 게임 소유 상태 확인
```

세부 절차: [references/unity-sample.md](references/unity-sample.md)

## 범용 진단

권장 Tool:

```text
runtime_status
runtime_build_info
runtime_logs_read
runtime_metrics_snapshot
runtime_capture_screenshot
```

사용 기준:

- Log: 오류·행동 흐름의 추가 증거
- Metrics: 성능 질문·전후 비교
- Screenshot: 화면 표현 검증
- Build Info: 오래된 실행 파일 여부 확인

범용 진단은 게임 권한 없음. 상세: [references/diagnostics.md](references/diagnostics.md)

## 검증

Tool 호출 성공과 게임 결과 성공의 분리.

```text
상태 변경
-> Action Result
-> 권위 상태 재조회
-> 필요 시 Log / Metrics / Screenshot
```

상세: [references/verification.md](references/verification.md)

## 금지 규칙

- Session Token 출력·요청·저장·노출 금지
- Timeout 발생 비멱등 행동의 즉시 재호출 금지
- Runtime 전송 경로를 통한 게임 파일 수정 금지
- 게임 소유 합법 행동 검증 우회 금지
- Screenshot·Log·Metrics를 권위 상태 대체 근거로 사용 금지
- 다른 Process·Session의 상태·Cursor 재사용 금지
