"""
Audison V2 TrustEngine — Basic usage examples

Before running:
1. Copy .env.example to .env and fill in your API keys
2. Single key works out of the box (brain2 auto-resolves)
3. Dual key recommended for best quality (cross-provider arbitration)
"""

import asyncio
from audison import TrustEngine


async def single_key_example():
    """Single API key — brain2 auto-resolves to a cheaper model from the same provider."""
    print("=== Single Key Example ===")
    print("One OpenAI key is enough. brain2 auto-selects gpt-4o-mini.")

    engine = TrustEngine()
    print("TrustEngine initialized (single-key mode)")

    code = '''
def login(username, password):
    query = "SELECT * FROM users WHERE name='" + username + "'"
    query += " AND password='" + hash(password) + "'"
    return db.execute(query)
'''
    print("\nAuditing code...")
    report = engine.audit(
        requirement="Secure user authentication with rate limiting",
        ai_output=code,
    )

    print("\n=== Audit Result ===")
    print(f"Verdict: {report.verdict}")
    print(f"Confidence: {report.confidence}/100")
    print(f"Findings: {len(report.findings)}")
    for f in report.findings:
        print(f"  - [{f.severity}] {f.description}")
    if report.uncertainty:
        print(f"Uncertain items: {len(report.uncertainty)}")


async def dual_key_example():
    """Dual API keys — brain2 uses a model from a different provider (recommended)."""
    print("\n=== Dual Key Example ===")
    print("OpenAI + Anthropic. Cross-provider arbitration = best quality.")

    engine = TrustEngine()
    print("TrustEngine initialized (dual-key mode)")

    code = '''
def process_payment(amount, card_number):
    api_key = "sk-live-abc123def456"
    response = requests.post("https://api.payment.com/charge",
        json={"amount": amount, "card": card_number},
        headers={"Authorization": f"Bearer {api_key}"})
    return response.json()
'''
    print("\nAuditing code...")
    report = engine.audit(
        requirement="Secure payment processing with PCI compliance",
        ai_output=code,
    )

    print("\n=== Audit Result ===")
    print(f"Verdict: {report.verdict}")
    print(f"Confidence: {report.confidence}/100")
    for f in report.findings:
        print(f"  - [{f.severity}] {f.description}")


async def cli_style_example():
    """Using TrustEngine in CLI-style mode (HTML report export)."""
    print("\n=== CLI-style Example ===")
    print("Equivalent to: audison audit code.py -r 'Security audit' --html -o report.html")

    engine = TrustEngine()
    report = engine.audit(
        requirement="Security audit: check for SQL injection, XSS, auth bypass",
        ai_output=open("example_requirement.txt").read() if __import__("os").path.exists("example_requirement.txt") else "placeholder code",
    )

    print(f"\nVerdict: {report.verdict} (confidence: {report.confidence}/100)")
    print(f"Evidence chain: {report.evidence_chain.hash[:16]}...")
    print(f"Timestamp: {report.evidence_chain.timestamp}")


async def main():
    print("Audison V2 TrustEngine - Usage Examples")
    print("=" * 50)

    try:
        await single_key_example()
        await dual_key_example()
        await cli_style_example()

        print("\n" + "=" * 50)
        print("Examples complete. See README.md for more usage patterns.")

    except Exception as e:
        print(f"\nNote: {e}")
        print("Examples require valid API keys in .env file.")
        print("For a quick try without API keys, visit:")
        print("  https://wdnmd1265.github.io/Audison/playground.html")


if __name__ == "__main__":
    asyncio.run(main())
