# Tool 입력 Schema 검증

GameRuntimeMcpHost는 `tools/call`의 `arguments`를 Runtime에 전달하기 전에 Tool Manifest의 `inputSchema`로 검사한다.

```text
MCP Client
-> tools/call
-> Host 입력 검증
   -> 실패: JSON-RPC -32602
   -> 성공: Runtime RPC 전달
```

Runtime Adapter의 게임 규칙 검증은 그대로 유지한다.

```text
Host Schema 검증
= 구조·자료형·기본 범위

Runtime Adapter 검증
= 권한·현재 상태·합법 행동·권위 상태 변경
```

## 지원 Schema 부분집합

의존성 없는 구현. 현재 저장소 Manifest가 사용하는 항목만 지원.

```text
type
properties
required
additionalProperties
items
enum
minimum / maximum
exclusiveMinimum / exclusiveMaximum
minLength / maxLength
minItems / maxItems
anyOf
```

허용 Annotation:

```text
$schema / $id
title / description / default / examples
deprecated / readOnly / writeOnly
```

지원하지 않는 Schema Keyword가 Manifest에 있으면 Host 시작 시 오류. 제약을 조용히 무시하지 않음.

## 오류 예

호출:

```json
{
  "name": "player_move_to",
  "arguments": {
    "targetX": 4
  }
}
```

응답:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32602,
    "message": "Invalid arguments for tool 'player_move_to': arguments.targetZ is required."
  }
}
```

이 경우 Unity Runtime RPC 호출 없음.

## 경계

Host 입력 검증만으로 게임 행동을 승인하지 않음.

예:

```text
좌표가 number
-> Host 통과

현재 맵에서 이동 가능한 좌표
-> 게임 Adapter 판정
```

Manifest와 Runtime Handler의 제한값은 같은 계약으로 유지.
