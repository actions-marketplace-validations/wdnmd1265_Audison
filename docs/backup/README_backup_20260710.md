<p align="center">
  <img src="docs/img/logo.svg" alt="Audison" width="500" />
</p>

<p align="center">
  <strong>AI wrote the code. Audison finds the bugs your AI reviewer missed.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/audison/"><img src="https://img.shields.io/badge/pypi-v2.3.4-3776AB.svg" alt="PyPI"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.9%2B-3776AB.svg" alt="Python 3.9+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-4CAF50.svg" alt="License"></a>
</p>

---

**Real numbers, not benchmarks.** Audison audited [httpx v0.28.1](https://github.com/encode/httpx) (GitHub 14,000+ Stars) across 10 security-critical functions.

| CONFIRMED | REFUTED | UNCERTAIN |
|:---------:|:-------:|:---------:|
| 5 | 4 | 1 |

[See the full report →](reports/real_world_audit.md)

```bash
pip install audison && audison scan .
```

---

## The Problem

A single model cannot discover its own blind spots. Your AI reviewer reads its own output with the same training data, the same biases, the same weak points. It's one person grading their own homework.

Audison makes two models argue — one audits, another attacks from adversary perspectives, and a third cross-validates. Consensus comes from surviving attack, not from agreeing to agree.

---

## What Audison Catches That Others Miss

Same AI-generated auth code, four reviewers:

| Finding | Standard AI Review | CodeQL / SAST | Shannon | Audison |
|---|---|---|---|---|
| SQL injection in login | Missed | Missed | Missed | Found |
| Hardcoded JWT secret | Warning | Missed | Missed | Found |
| Missing rate limiting | Missed | Missed | Missed | Found |
| CSRF token bypass | Missed | Missed | Missed | Found |

---

## How It Works

```
Input Code
    │
    ▼
[ Brain One ]  ──── Primary audit: identifies issues across security,
  (GPT-4o)           correctness, and logic dimensions.
    │
    ▼
[ Opponent Brain ] ──── 5 adversarial perspectives attack the output.
  (Claude Sonnet)        Confirms or disputes each finding.
    │
    ▼
[ Brain Two ]  ──── Cross-verification. Consensus → confirmed.
                     Disagreement → UNCERTAIN, not hidden.
    │
    ▼
[ TrustReport ]  ──── Verdict (pass / review / reject) +
                       Confidence score + Findings +
                       SHA-256 evidence chain + Timestamp
```

---

## Quick Start

```bash
# 1. Install
pip install audison

# 2. Scan
audison scan .

# 3. Read the report
# Terminal output with color-coded findings, or:
audison scan . --output report.md
```

Set one API key — or two for cross-provider arbitration (recommended):

```bash
export OPENAI_API_KEY="sk-..."         # Required
export ANTHROPIC_API_KEY="sk-ant-..."   # Optional, for stronger audits
```

---

## Comparison

| Feature | Audison | Standard AI Review | CodeQL | Shannon |
|---------|:-------:|:------------------:|:------:|:-------:|
| Open Source | Yes | — | Yes | No |
| Multi-model Arbitration | Yes | No | No | Yes |
| Adversarial Review | Yes | No | No | No |
| Uncertainty Transparency | Yes | No | No | No |
| Verifiable Evidence Chain | Yes | No | No | No |
| Cost | Free; your API keys | Free | Free | Subscription |

---

## Project Structure

```
audison/
├── src/audison/
│   ├── engine/              # TrustEngine — standalone audit layer
│   ├── brains/              # Brain One, Brain Two, Opponent Brain
│   ├── core/                # Caching, context, session management
│   └── utils/               # LLM client (8 providers), token counter
├── tests/unit/              # 186 unit tests
├── reports/                 # Audit reports
├── docs/                    # API, integrations, getting started
├── pyproject.toml
└── LICENSE
```

---

## License

[Apache License 2.0](LICENSE) — Copyright 2026 盛鑫

---

<p align="center">
  <em>AI proposes. AI challenges. You decide.</em>
</p>

<p align="center">
  <a href="https://wdnmd1265.github.io/Audison/playground.html"><strong>Try it live: playground.html</strong></a>
  &nbsp;|&nbsp;
  <a href="https://wdnmd1265.github.io/Audison/">GitHub Pages</a>
</p>

---

**详细文档见 [docs/](docs/)** — API 详解、MCP Server 配置、GitHub Action、LangChain/CrewAI 集成等。
