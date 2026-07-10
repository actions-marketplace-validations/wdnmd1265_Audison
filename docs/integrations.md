# Integrations

## MCP Server (Cursor / Claude Desktop)

Configure in your AI editor's `mcp.json`:

```json
{
  "mcpServers": {
    "audison": {
      "command": "uvx",
      "args": ["audison[mcp]", "audison-mcp"],
      "env": {
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

Then use `audit_code` and `audit_file` tools directly in your AI assistant to verify AI-generated code before it enters your codebase.

## GitHub Action

Automatically audit AI-generated code in every pull request. Two independent AI models cross-verify your code changes and post the result directly as a PR comment.

### Quick Start

1. Copy the example workflow to your repository:

```bash
cp .github/workflows/ai-audit.yml.example .github/workflows/ai-audit.yml
```

2. Add at least one API key as a repository secret:

`Settings → Secrets and variables → Actions → New repository secret`

| Secret | Required | Description |
|--------|----------|-------------|
| `OPENAI_API_KEY` | Recommended | Primary audit model (GPT-4o) |
| `ANTHROPIC_API_KEY` | Optional | Secondary model (Claude) for cross-provider verification |

3. Create a pull request — the audit runs automatically and posts a comment.

### Configuration

| Input | Default | Description |
|-------|---------|-------------|
| `brain1` | `gpt-4o` | Primary audit model |
| `brain2` | `claude-3-5-sonnet` | Secondary audit model |
| `path` | changed files | File or directory to audit |
| `requirement` | — | Custom audit requirement |
| `fail_on` | `never` | Fail workflow: `reject` / `review` / `never` |
| `comment_mode` | `both` | Display: `pr` / `summary` / `both` |
| `api_key_openai` | — | OpenAI API Key |
| `api_key_anthropic` | — | Anthropic API Key |

### Multi-Provider Support

Audison supports 10 API providers. Set any of these additional secrets to enable more models:

`DASHSCOPE_API_KEY` · `DEEPSEEK_API_KEY` · `GOOGLE_API_KEY` · `ZHIPU_API_KEY` · `MOONSHOT_API_KEY` · `MIMO_API_KEY` · `NVIDIA_API_KEY` · `CUSTOM_API_KEY`

## LangChain Integration

```python
from langchain.agents import AgentExecutor
from audison import TrustEngine

agent = AgentExecutor.from_agent_and_tools(agent=my_agent, tools=my_tools)
engine = TrustEngine()

result = agent.run("Write a login function")
report = engine.audit(
    requirement="Secure user authentication with rate limiting",
    ai_output=result,
)
print(report.summary())
```

## CrewAI Integration

```python
from crewai import Crew
from audison import TrustEngine

crew = Crew(agents=[dev_agent], tasks=[dev_task])
engine = TrustEngine()

output = crew.kickoff()
report = engine.audit(
    requirement="Production-grade login endpoint",
    ai_output=output,
)
```

## OpenAI SDK Integration

```python
from openai import OpenAI
from audison import TrustEngine

client = OpenAI()
engine = TrustEngine()

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Write a payment processing function"}],
)
report = engine.audit(
    requirement="PCI-compliant payment processing",
    ai_output=response.choices[0].message.content,
)
```

## Local Mode (Ollama)

For privacy-sensitive workflows, use local models via Ollama. Code never leaves your machine.

```bash
# Install Ollama
# macOS / Linux:  curl -fsSL https://ollama.com/install.sh | sh
# Windows:        https://ollama.com/download

# Pull models
ollama pull llama3
ollama pull codellama

# Run audit locally
audison audit your_code.py -r "requirement" --local

# Or specify custom models
audison audit your_code.py -r "requirement" --local --model1 llama3 --model2 codellama
```

> **Accuracy Note**: Local models (~50-60% detection rate) are significantly less accurate than cloud models (85%+). Use local mode when code privacy is critical, but use cloud mode for production audit quality.

## Model Selection Guide

Use **[Compass](https://github.com/yourusername/compass)** to predict pairing gains before spending on API calls.

```bash
pip install compass
compass diagnose --models gpt-4o,claude-sonnet,deepseek
# Recommends optimal pairs based on SDT theory
```

Compass analyzes Signal Detection Theory parameters (d', c) to predict complementarity gains:

- Find models with different criterion values (c) for better complementarity
- Avoid redundant model combinations that echo the same blind spots
- Maximize detection rate while minimizing API costs

**Example workflow**:

```bash
# Step 1: Diagnose your model pool
compass diagnose --models gpt-4o,claude-sonnet,deepseek
# Output: Best pair: gpt-4o + deepseek (predicted CG: 0.24)

# Step 2: Use recommended pair in Audison
audison audit code.py --brain1 gpt-4o --brain2 deepseek
```
