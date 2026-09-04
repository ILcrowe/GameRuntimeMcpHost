# 에이전트 스킬 설치

이 저장소는 [`game-runtime-mcp-host`](game-runtime-mcp-host)에 낮은 추론량용 런타임 스킬을 포함한다.

이 스킬은 에이전트가 다음을 수행하도록 고정한다.

- 실행 중인 빌드 Player 작업과 Unity Editor 작업 구분
- 기존 GameRuntimeMcpHost 세션 절차를 통한 연결·복구
- 범용 진단보다 정확한 게임 소유 명령 우선
- 상태 변경 행동 뒤 결과 검증
- 타임아웃 뒤 위험한 재시도 방지
- 빌드 식별, 제한된 로그, 메트릭, 스크린샷을 증거가 될 때만 사용

CLI 계층이나 두 번째 런타임 전송 경로를 추가하지 않는다.

## Codex 프로젝트 로컬 설치

PowerShell에서 실행한다.

```powershell
& "C:\path\to\GameRuntimeMcpHost\skills\install-codex.ps1" `
  -TargetProject "C:\path\to\YourUnityProject"
```

다음 위치로 스킬을 복사한다.

```text
<YourUnityProject>/.agents/skills/game-runtime-mcp-host/
```

이미 설치된 스킬을 교체하려면 `-Force`를 사용한다.

설치 또는 교체 뒤 Codex가 프로젝트 로컬 스킬을 다시 읽도록 새 세션을 연다.

## 수동 설치

`game-runtime-mcp-host` 디렉터리 전체를 대상 클라이언트의 프로젝트 로컬 스킬 디렉터리에 복사한다. `SKILL.md`와 `references` 디렉터리를 함께 유지한다.

MCP 서버 등록과 스킬은 서로 다른 역할이다.

```text
MCP 등록 = 호출 가능한 도구
에이전트 스킬 = 라우팅 및 운용 절차
```

낮은 추론량에서 일관되게 런타임을 운용하려면 둘 다 필요하다.
