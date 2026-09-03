# Changelog

All notable changes to this project are documented in this file.

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
