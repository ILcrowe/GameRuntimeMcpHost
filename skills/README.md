# Agent Skill 설치

낮은 추론량용 Runtime Skill:

```text
skills/game-runtime-mcp-host/
├─ SKILL.md
└─ references/
   ├─ connection.md
   ├─ diagnostics.md
   ├─ gameplay-control.md
   ├─ unity-sample.md
   └─ verification.md
```

## 역할

```text
실행 중 Player와 Editor 작업 분리
Runtime 연결·복구
정확한 게임 소유 Tool 우선
상태 변경 전후 검증
Timeout 뒤 위험한 재시도 방지
필요한 진단만 사용
```

CLI 계층·두 번째 Runtime 전송 경로 추가 없음.

## Codex 프로젝트 로컬 설치

```powershell
& "C:\path\to\GameRuntimeMcpHost\skills\install-codex.ps1" `
  -TargetProject "C:\path\to\YourUnityProject"
```

설치 위치:

```text
<YourUnityProject>/.agents/skills/game-runtime-mcp-host/
```

기존 설치본 교체:

```powershell
& "C:\path\to\GameRuntimeMcpHost\skills\install-codex.ps1" `
  -TargetProject "C:\path\to\YourUnityProject" `
  -Force
```

설치 뒤 새 Codex Session.

## 수동 설치

`game-runtime-mcp-host` 전체 폴더를 프로젝트의 `.agents/skills/` 아래에 복사. `SKILL.md`와 `references/` 동시 유지.

```text
MCP 등록 = 호출 가능한 Tool
Agent Skill = Tool 선택·재시도·검증 절차
```
