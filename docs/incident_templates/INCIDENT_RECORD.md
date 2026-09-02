# Incident Record

> 不得粘贴密码、Cookie、验证码、Authorization、API Secret、付费全文或个人信息。

## Identity

- Incident ID:
- Severity: `SEV0 | SEV1 | SEV2 | SEV3`
- State: `OPEN`
- Opened at UTC:
- Incident commander:
- Affected environment: `PAPER | SHADOW | TESTNET`

## Impact and evidence

- Affected accounts/scopes:
- Strategies/models/data sources/orders:
- First known bad time / last known good time:
- Correlation IDs / trace IDs:
- Metrics, log query and artifact hashes:
- Risk posture and automatic actions:

## Timeline

| UTC | State | Actor | Evidence-backed action |
|---|---|---|---|
| | OPEN | | |

Allowed lifecycle: `OPEN → ACKNOWLEDGED → MITIGATING → MONITORING → RESOLVED →
POSTMORTEM_REQUIRED → CLOSED`. `MONITORING → MITIGATING` is allowed on recurrence; other backward jumps are not.

## Recovery gate

- [ ] Root failure contained
- [ ] No new risk added during incident
- [ ] Ledger and reconciliation verified
- [ ] Data/checkpoint/replay verified
- [ ] Rollback or fix artifact signature verified
- [ ] Human approval recorded
- [ ] Live remains locked
