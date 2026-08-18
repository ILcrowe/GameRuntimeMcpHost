# Contributing

GameRuntimeMcpHost accepts focused fixes and transport-level improvements. Game rules and product-specific authority belong in each runtime adapter or tool manifest.

## Development setup

```powershell
git clone https://github.com/lLcrowe/GameRuntimeMcpHost.git
cd GameRuntimeMcpHost
python -m pip install -e .
python -m unittest discover -s tests -v
```

## Contribution rules

1. Keep the host dependency-free unless a dependency is essential to the MCP transport contract.
2. Preserve loopback-only endpoint validation and never expose session tokens in logs or MCP responses.
3. Put game-specific command names and schemas in a tool manifest, not in the host.
4. Add or update tests for behavior changes.
5. Update `CHANGELOG.md` when a user-visible contract changes.

Open an issue before proposing a breaking protocol or manifest change.
