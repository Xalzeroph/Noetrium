# Concurrency Governance Report

- Source digest: `7dccc9108cffb2c1ba769e86323c4d9081b269a2b61e082b417bff643fca117a`
- Hotspots: **286**
- Findings: **1**
- P0/P1 debt: **0**

## Coverage

| Language | Files | Hotspots | Parse errors |
|---|---:|---:|---:|
| javascript | 8 | 8 | 0 |
| python | 2444 | 277 | 0 |
| shell | 2 | 1 | 0 |

## Finding summary

| Code | Count |
|---|---:|
| `timeoutless-wait` | 1 |

## Hotspots

### `noetrium_platform/infrastructure/lifecycle/server/identity/providers/ssh.py::SSHServerConnection.run_interactive`
- **P2** `timeoutless-wait` line 371: blocking wait has no explicit deadline/timeout
