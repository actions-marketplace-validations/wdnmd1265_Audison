"""CLI command: calibrate — analyze codebase patterns and recommend optimal audit strategy.

Usage:
    audison calibrate [DIR] [--sample N] [--models MODEL_A MODEL_B]

The calibrate command:
  1. Samples code files from the target directory
  2. Classifies them by loop type (LINEAR / FOR_SIMPLE / FOR_NESTED / WHILE / LISTCOMP_ONLY)
  3. Runs dual-model audit consistency analysis
  4. Outputs a recommendation: single-model vs. multi-model strategy
"""

import asyncio
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box


def do_calibrate(args):
    """Entry point for `audison calibrate`."""
    console = Console()

    target_dir = Path(args.dir).resolve() if args.dir else Path.cwd()
    sample_n = getattr(args, "sample", 30)
    models = getattr(args, "models", None)

    # Default model pair
    if models and len(models) >= 2:
        model_a, model_b = models[0], models[1]
    else:
        model_a = "gpt-4o"
        model_b = "claude-sonnet-4-20250514"

    console.print()
    console.print(Panel.fit(
        Text("Audison Calibrate — Codebase Audit Strategy Optimizer", style="bold white"),
        border_style="cyan",
        padding=(1, 4),
    ))
    console.print(f"  Target:     [cyan]{target_dir}[/cyan]")
    console.print(f"  Sample:     up to [yellow]{sample_n}[/yellow] files")
    console.print(f"  Models:     [green]{model_a}[/green] vs [green]{model_b}[/green]")
    console.print()

    # Phase 1: Sampling
    with console.status("[bold cyan]Phase 1/4: Sampling code files...[/bold cyan]"):
        from ..engine.calibrate import sample_codebase

        samples = sample_codebase(str(target_dir), n=sample_n)

    if not samples:
        console.print("[red]No code files found in the target directory.[/red]")
        return

    console.print(f"  [green]Sampled {len(samples)} files[/green]")

    # Phase 2: Classification
    with console.status("[bold cyan]Phase 2/4: Classifying loop types...[/bold cyan]"):
        from ..engine.calibrate import classify_samples

        classification = classify_samples(samples)

    loop_dist = classification["distribution"]
    console.print(f"  [green]Classified {classification['total']} files[/green]")

    # Phase 3: Consistency analysis (async)
    console.print()
    console.print("[bold]Phase 3/4: Running dual-model consistency analysis...[/bold]")
    console.print("  (This may take 1-3 minutes depending on sample size)")
    console.print()

    try:
        from ..engine.calibrate import analyze_consistency

        consistency = asyncio.run(
            analyze_consistency(samples, model_a, model_b, max_samples=sample_n)
        )

        if consistency.get("errors"):
            console.print(f"  [yellow]Warning: {len(consistency['errors'])} model call(s) failed[/yellow]")
            for err in consistency["errors"][:3]:
                console.print(f"    [dim]- {err}[/dim]")
            if len(consistency["errors"]) > 3:
                console.print(f"    [dim]... and {len(consistency['errors']) - 3} more[/dim]")

        valid = consistency["total_compared"]
        if valid == 0:
            console.print("[red]All model calls failed. Cannot compute consistency.[/red]")
            console.print("[yellow]Check your API keys and network connectivity.[/yellow]")
            return

        console.print(f"  [green]Compared {valid} samples[/green]")

    except Exception as e:
        console.print(f"[red]Consistency analysis failed: {e}[/red]")
        console.print("[yellow]Proceeding with loop distribution only.[/yellow]")
        consistency = {
            "model_a": model_a,
            "model_b": model_b,
            "agreement_rate": 0.0,
            "total_compared": 0,
            "details": [],
            "errors": [str(e)],
        }

    # Phase 4: Recommendation
    from ..engine.calibrate import recommend_pairing

    recommendation = recommend_pairing(consistency, loop_dist)

    # ── Render Report ──
    _render_report(console, target_dir, classification, consistency, recommendation)


def _render_report(
    console: Console,
    target_dir: Path,
    classification: dict,
    consistency: dict,
    recommendation: dict,
):
    """Render the calibration report with color-coded terminal output."""
    loop_dist = classification["distribution"]

    # ── Section 1: Codebase Overview ──
    console.print()
    console.print(Panel.fit(
        Text("Calibration Report", style="bold white"),
        border_style="cyan",
        padding=(1, 4),
    ))

    overview = Table(title="Codebase Overview", box=box.SIMPLE, show_header=False)
    overview.add_column(style="bold", width=28)
    overview.add_column()
    overview.add_row("Target directory", str(target_dir))
    overview.add_row("Files sampled", str(classification["total"]))
    overview.add_row("Model pair", f"{consistency.get('model_a', '?')} vs {consistency.get('model_b', '?')}")
    console.print(overview)

    # ── Section 2: Loop Type Distribution ──
    console.print()
    console.print(Text("Loop Type Distribution", style="bold"))

    loop_table = Table(box=box.SIMPLE)
    loop_table.add_column("Loop Type", style="bold")
    loop_table.add_column("Percentage", justify="right")
    loop_table.add_column("Bar")
    loop_table.add_column("Assessment")

    thresholds = {
        "LINEAR": (0, 100, "Single-model friendly"),
        "FOR_SIMPLE": (0, 100, "Moderate; >25% triggers dual-model"),
        "FOR_NESTED": (0, 100, "Single-model handles well"),
        "WHILE": (0, 100, "Single-model handles well"),
        "LISTCOMP_ONLY": (0, 100, "High risk; >15% triggers dual-model"),
    }

    for lt in ("LINEAR", "FOR_SIMPLE", "FOR_NESTED", "WHILE", "LISTCOMP_ONLY"):
        pct = loop_dist.get(lt, 0.0)
        bar = _make_bar(pct)

        if lt == "LISTCOMP_ONLY" and pct > 15.0:
            style = "red"
            assessment = f"[red]EXCEEDS 15% threshold[/red]"
        elif lt == "FOR_SIMPLE" and pct > 25.0:
            style = "yellow"
            assessment = f"[yellow]EXCEEDS 25% threshold[/yellow]"
        elif lt in ("LINEAR", "FOR_NESTED", "WHILE"):
            style = "green"
            assessment = "[green]OK[/green]"
        else:
            style = "dim"
            assessment = thresholds[lt][2]

        loop_table.add_row(
            lt,
            f"{pct:.1f}%",
            f"[{style}]{bar}[/{style}]",
            assessment,
        )

    console.print(loop_table)

    # ── Section 3: Model Consistency ──
    console.print()
    console.print(Text("Model Consistency Analysis", style="bold"))

    agreement = consistency.get("agreement_rate", 0)
    total = consistency.get("total_compared", 0)

    if total > 0:
        if agreement >= 0.80:
            agreement_color = "green"
        elif agreement >= 0.50:
            agreement_color = "yellow"
        else:
            agreement_color = "red"

        cons_table = Table(box=box.SIMPLE, show_header=False)
        cons_table.add_column(style="bold", width=28)
        cons_table.add_column()
        cons_table.add_row("Model A", consistency.get("model_a", "?"))
        cons_table.add_row("Model B", consistency.get("model_b", "?"))
        cons_table.add_row("Samples compared", str(total))
        cons_table.add_row(
            "Agreement rate",
            f"[{agreement_color}]{agreement:.1%}[/{agreement_color}]",
        )
        cons_table.add_row(
            "Interpretation",
            _agreement_interpretation(agreement),
        )
        console.print(cons_table)

        # Detail breakdown
        details = consistency.get("details", [])
        if details:
            agree_count = sum(1 for d in details if d.get("agreed"))
            disagree_count = total - agree_count
            console.print()
            console.print(f"  Agreed:  [green]{agree_count}[/green] samples")
            console.print(f"  Disagreed: [red]{disagree_count}[/red] samples")
    else:
        console.print("  [yellow]No valid comparisons (all model calls failed)[/yellow]")

    # ── Section 4: Recommendation ──
    console.print()
    console.print(Text("Recommended Strategy", style="bold"))

    single_sufficient = recommendation.get("single_model_sufficient", False)
    rec_pair = recommendation.get("recommended_pair")
    savings = recommendation.get("estimated_api_savings", "N/A")
    rationale = recommendation.get("rationale", "")

    if single_sufficient and rec_pair is None:
        strategy_color = "green"
        strategy_label = "SINGLE MODEL"
        strategy_desc = "Your codebase is dominated by loop types that single models handle well. Using a single model will cut API costs by ~50% without sacrificing audit quality."
    else:
        strategy_color = "yellow"
        strategy_label = "DUAL MODEL"
        strategy_desc = "Your codebase contains loop patterns that benefit from multi-model cross-validation. Dual models provide better coverage for these complex patterns."

    rec_panel = Panel.fit(
        f"[bold {strategy_color}]{strategy_label}[/bold {strategy_color}]\n\n"
        f"{strategy_desc}\n\n"
        f"Recommended pair: [bold]{rec_pair or 'N/A (single model sufficient)'}[/bold]\n"
        f"Estimated API savings: [bold]{savings}[/bold]\n\n"
        f"[dim]Rationale: {rationale}[/dim]",
        border_style=strategy_color,
        title="Recommendation",
    )
    console.print(rec_panel)
    console.print()


def _make_bar(pct: float, width: int = 20) -> str:
    """Create a simple ASCII bar for the given percentage."""
    filled = int(round(pct / 100 * width))
    return "█" * filled + "░" * (width - filled)


def _agreement_interpretation(rate: float) -> str:
    """Human-readable interpretation of agreement rate."""
    if rate >= 0.90:
        return "[green]Very high agreement — dual models add limited value[/green]"
    elif rate >= 0.80:
        return "[green]High agreement — single model likely sufficient[/green]"
    elif rate >= 0.60:
        return "[yellow]Moderate agreement — dual models provide some value[/yellow]"
    elif rate >= 0.40:
        return "[yellow]Low agreement — dual models add meaningful divergence[/yellow]"
    else:
        return "[red]Very low agreement — models disagree heavily, dual models critical[/red]"
