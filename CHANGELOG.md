# Changelog

All notable changes to this project are documented in this file.

## 미출시

- Unity 게임 상태 조회, 주변 탐색, 실제 샘플 이동, 명시적 상호작용, 인게임 채팅을 제공하는 등록형 게임 플레이 샘플을 추가했습니다.
- 게임 플레이 샘플 Bridge를 현재 Host의 `protocol` / `command` / `payload` RPC 계약과 일치시켰습니다.
- 세션별 토큰, 제한된 요청 Body, 메인 스레드 처리 예산, Timeout 상태 구분, 안전한 Listener 종료를 적용했습니다.
- 낮은 추론량 Skill에 게임 플레이 샘플의 연결·이동·상호작용·검증 순서를 추가했습니다.
- 게임 플레이 도구 매니페스트 정적 계약 테스트와 인증·상태·이동·상호작용·채팅 PlayMode 왕복 테스트를 추가했습니다.

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
