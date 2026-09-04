# 런타임 검증

요청 결과를 증명하는 최소 근거 사용.

## 상태 변경

```text
변경 전 관련 상태
-> 행동 1개
-> Action Result
-> 같은 상태 재조회
-> 기대값·실제값 비교
```

## 화면 변경

```text
논리·권위 상태 확인
-> Screenshot 1회
-> 표현 확인
```

Screenshot 단독으로 Serialized·Runtime 상태 판정 금지.

## 성능 변경

```text
Build Identity
-> 동일 조건 Baseline Metrics
-> 변경 반영
-> 새 Build 재연결
-> Build Identity 변경 확인
-> 동일 조건 Metrics
-> 같은 항목 비교
```

## 실패 근거 우선순위

1. 권위 상태·Action Result
2. Runtime Error Payload
3. 필터된 증분 Log
4. 성능 관련 Metrics
5. 표현 관련 Screenshot

모든 진단면의 기본 수집 금지.
