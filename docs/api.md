# TrustEngine API

TrustEngine is the standalone audit layer. Zero state. Zero interaction. Pure verification.

## Quick Example

```python
from audison.engine import TrustEngine
import asyncio

async def main():
    engine = TrustEngine(brain1="gpt-4o", brain2="claude-3-5-sonnet")
    report = await engine.audit(
        requirement="Design a user management system",
        ai_output="def login(user, pwd): query = 'SELECT * FROM users WHERE name=\\'\" + user + \"\\''",
    )

    print(report.summary())
    # REJECT | Confidence 32/100 | 3 findings | 2 risks | 1 uncertain

asyncio.run(main())
```

## Report Schema

```python
report.verdict        # "pass" | "review" | "reject"
report.confidence     # 0-100
report.findings       # Specific issues with severity + evidence
report.uncertainty    # What the engine admits it cannot confirm
report.evidence_chain # SHA-256 hash + timestamp, fully verifiable
```

## Constructor

```python
TrustEngine(
    brain1="gpt-4o",           # Primary audit model
    brain2="claude-3-5-sonnet", # Secondary cross-verification model
    opponent_brain=None,        # Optional: custom opponent model (defaults to brain2)
    blind_review=False,         # Experimental: context-free final review
    cache_enabled=True,         # Enable evidence chain caching
)
```

## audit() Method

```python
async def audit(
    requirement: str,   # Audit requirement / specification
    ai_output: str,     # AI-generated code or text to audit
    context: Optional[AuditContext] = None,  # Project metadata
) -> TrustReport
```

## Output Formats

| Format | Command | Use Case |
|--------|---------|----------|
| Terminal | `audison audit ...` | Interactive, color-coded |
| HTML | `audison audit ... --html -o report.html` | Share with team, post in issues |
| JSON | `audison audit ... --json` | Pipe to other tools, CI/CD |
| Markdown | `audison audit ... --markdown` | Embed in docs, PR comments |

## TrustReport

### Verdict

| Verdict | Meaning |
|---------|---------|
| `pass` | No significant issues found |
| `review` | Issues found, manual review recommended |
| `reject` | Critical issues found, do not merge |

### Confidence Score

A 0-100 score representing the engine's confidence in its verdict. Based on:

- Inter-model agreement level
- Evidence chain completeness
- Finding severity distribution

### Findings

Each finding includes:

- **Severity**: `critical` / `high` / `medium` / `low`
- **Category**: security / correctness / logic / performance
- **Evidence**: code references and reasoning
- **Arbiter Vote**: which model confirmed or disputed the finding

### Uncertainty

When Brain One and the Opponent Brain disagree, the finding is flagged as UNCERTAIN with both positions quoted. Audison does not hide disagreement — you decide.

### Evidence Chain

Every finding is hashed with SHA-256 and timestamped. The evidence chain provides:

- Cryptographic proof of what was found and when
- Tamper-proof audit trail
- Shareable verification (hash proves the report hasn't been modified)

## Python SDK (3 lines)

```python
from audison import TrustEngine

engine = TrustEngine()
report = engine.audit(
    requirement="Secure user authentication with rate limiting",
    ai_output=ai_generated_code,
)
print(report.summary())  # "REJECT (32/100): 3 findings, 2 uncertain"
```
