# Static analysis: p09-unsafe-fixture

- Artifact SHA-256: `4b929b6f72162b911a0b67417af637a3c48d3d13fd95561c0645768fff4474cd`
- Review state: `QUARANTINED`
- Executable allowed: `false`
- Source executed: `false`

| Severity | Category | Line | Symbol | Message |
|---|---|---:|---|---|
| HIGH | subprocess_import | 3 | `subprocess` | subprocess module imported |
| HIGH | network_import | 5 | `requests` | network-capable module imported |
| CRITICAL | embedded_credential | 7 | `API_TOKEN_REFERENCE` | secret-like global assignment detected; value intentionally not reported |
| HIGH | file_write | 9 | `open` | filesystem write detected |
| HIGH | network_call | 10 | `requests.get` | network-capable call detected |
| CRITICAL | subprocess | 11 | `subprocess.run` | process execution detected |
| HIGH | unsafe_deserialization | 12 | `pickle.loads` | unsafe or code-capable deserialization detected |
| CRITICAL | dynamic_execution | 13 | `eval` | dynamic code execution detected |
| CRITICAL | destructive_file_operation | 14 | `os.remove` | destructive file operation detected |

该报告只来自 AST/格式解析，未导入或执行来源代码。
