# Changelog

All notable changes to this project are documented in this file.

## 미출시

- Tool Manifest `inputSchema`의 의존성 없는 부분집합을 Host에서 사전 검증
- 잘못된 Tool 인자의 Runtime 전달 차단과 JSON-RPC `-32602` 응답
- `--session-instance`·`--session-role` 기반 다중 Runtime 선택
- 기본 Session 이름과 접미사형 Session 파일 동시 검색
- 구형 Unity 샘플 경로를 참조하던 Host 테스트 제거
- Windows Python 구문 검사·단위 테스트 GitHub Actions
- 공통 `GameRuntimeMcpBridge` 기반 Unity 통합 샘플
- Owner 단위 원자적 `RegisterAll`·`UnregisterAll` 명령 등록
- 게임 상태·주변 조회·이동·상호작용·채팅 샘플
- Bridge 내장 Build·Log·Metrics·Screenshot 진단
- 실행별 Token·Loopback Listener·메인 스레드 처리 예산
- 시작 전 Timeout과 실행 여부 불명 Timeout 구분
- 한글 XML Summary 주석과 한글 중심 연동 문서
- 낮은 추론량 연결·행동·검증 Skill
- 통합 Tool Manifest 정적 계약 테스트
- 연결·진단·게임 행동 PlayMode 왕복 테스트
- 중복 Unity Bridge·진단 Provider·게임 플레이 샘플 폴더 제거

## 0.3.0 — 2026-09-04

- Added provider-neutral JSON-RPC subprocess, session-descriptor, and append-only audit-stream primitives.
- Added a reusable persistent Codex app-server adapter with isolated utility threads.
- Added a resumable Grok Build headless adapter using `--output-format json`, `--json-schema`, and `--resume` rather than a consumer-owned ACP lifecycle.
- Added save-scope-friendly provider session persistence and isolated Grok homes that copy authentication without inheriting personal MCP/plugin configuration.
- Added regression coverage for provider session persistence, Grok resume recovery, utility isolation, and ACP permission rejection.

## 0.2.0 — 2026-08-19

- Added a copy-ready Unity C# runtime adapter sample with explicit scene placement, loopback token authentication, bounded main-thread dispatch, a companion tool manifest, and a PlayMode round-trip test.
- Added English and Korean Unity sample setup, extension, and security guidance.

## 0.1.0 — 2026-08-18

- Published the dependency-free MCP stdio host as an independent project.
- Added explicit loopback-only endpoint validation and per-session token forwarding.
- Rejected runtime HTTP redirects so session credentials remain inside the loopback boundary.
- Added session rediscovery for Unity runtime restarts.
- Added example manifests for generic runtimes, StoryLLMMaster, and LLMConversationRuntime.
- Added English and Korean setup, configuration, security, and troubleshooting documentation.
