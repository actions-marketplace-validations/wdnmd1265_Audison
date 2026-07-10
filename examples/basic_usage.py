"""
Basic usage examples for Audison

Before running:
1. Copy .env.example to .env and fill in your API keys
2. Single key works out of the box (brain2 auto-resolves)
3. Dual key recommended for best quality (cross-provider arbitration)
"""

import asyncio
from audison.engine import TrustEngine


async def single_key_example():
    """Single API key — brain2 auto-resolves to a cheaper model from the same provider."""
    print("=== Single Key Example ===")
    print("One OpenAI key is enough. brain2 auto-selects gpt-4o-mini.")

    engine = TrustEngine(brain1="gpt-4o")
    print(f"TrustEngine initialized with brain1=gpt-4o")

    requirement = "Design a user management system"
    ai_output = """
def login(username, password):
    query = "SELECT * FROM users WHERE name='" + username + "'"
    return db.execute(query)
"""

    print(f"\nAuditing AI output...")
    report = await engine.audit(requirement=requirement, ai_output=ai_output)

    print(f"\n=== Result ===")
    print(report.summary())


async def dual_key_example():
    """Dual API keys — brain2 uses a model from a different provider (recommended)."""
    print("=== Dual Key Example ===")
    print("OpenAI + Anthropic. Cross-provider arbitration = best quality.")

    engine = TrustEngine(brain1="gpt-4o", brain2="claude-3-5-sonnet-20241022")
    print("TrustEngine initialized with cross-provider models")

    requirement = "Design a user management system"
    ai_output = """
def login(username, password):
    query = "SELECT * FROM users WHERE name='" + username + "'"
    return db.execute(query)
"""

    print(f"\nAuditing AI output...")
    report = await engine.audit(requirement=requirement, ai_output=ai_output)

    print(f"\n=== Result ===")
    print(report.summary())


async def cli_example():
    """CLI usage example"""
    print("=== CLI Example ===")
    print("""
# One-liner audit:
audison audit login.py -r "Check for SQL injection and auth bypass"

# With HTML export:
audison audit login.py -r "Security audit" --html -o report.html

# Pipe from stdin:
cat generated_code.py | audison audit -r "Validate correctness"
""")


async def main():
    print("Audison - Usage Examples")
    print("=" * 50)

    try:
        await dual_key_example()
        await cli_example()

        print("\n" + "=" * 50)
        print("Examples complete")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
