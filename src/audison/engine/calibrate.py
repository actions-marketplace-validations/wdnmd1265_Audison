"""
Codebase Calibration Engine — analyze codebase loop type distribution and model pairing consistency
to recommend optimal single-model vs multi-model audit strategies.

Key metrics:
- Loop type distribution: which loop patterns dominate the codebase
- Model pairing consistency: how often two models agree on audit verdicts
- Single-model sufficiency: LINEAR + FOR_NESTED + WHILE > 85% → single model is sufficient
- Multi-model requirement: LISTCOMP_ONLY > 15% or FOR_SIMPLE > 25% → dual models recommended
"""

import os
import ast
import random
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from loguru import logger

from .complexity_router import classify_loop_type

# Default audit prompt for calibration — minimal, consistent, and deterministic
_CALIBRATION_AUDIT_PROMPT = (
    "You are a code reviewer. Review the following code for bugs, security issues, "
    "and code quality problems. Respond with exactly one word: PASS if the code is acceptable, "
    "or FAIL if it has significant issues. Do not explain your reasoning.\n\n"
    "Code:\n```\n{code}\n```"
)


def sample_codebase(
    root_dir: str,
    n: int = 50,
    exts: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Randomly sample up to n source files from root_dir.

    Walks the directory tree, filters by extension, and randomly selects
    up to n files. Each sample includes the file path and its text content.

    Args:
        root_dir: Root directory to scan.
        n: Maximum number of files to sample (default 50).
        exts: List of extensions to include, e.g. ['.py', '.js'].
              Defaults to ['.py'].

    Returns:
        List of dicts with keys: path (str), content (str).
    """
    if exts is None:
        exts = [".py"]

    root = Path(root_dir).resolve()
    if not root.exists():
        logger.warning(f"Directory not found: {root_dir}")
        return []

    # Collect all matching files
    all_files: List[Path] = []
    skip_dirs = {
        ".git", ".svn", "__pycache__", "venv", ".venv",
        "node_modules", "dist", "build", ".tox", "egg-info",
        ".eggs", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    }

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip hidden and build directories
        dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fpath.suffix.lower() in exts:
                all_files.append(fpath)

    logger.info(f"Found {len(all_files)} matching files in {root_dir}")

    if len(all_files) <= n:
        sampled = all_files
    else:
        sampled = random.sample(all_files, n)

    # Read content for each sampled file
    samples: List[Dict[str, Any]] = []
    for fpath in sampled:
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
            samples.append({"path": str(fpath), "content": content})
        except Exception as e:
            logger.warning(f"Failed to read {fpath}: {e}")

    logger.info(f"Sampled {len(samples)} files from {len(all_files)} total")
    return samples


def classify_samples(
    samples: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Classify each sample by its dominant loop type using AST analysis.

    Returns per-sample classifications and an aggregate distribution
    (percentage of each loop type).

    Args:
        samples: List of sample dicts from sample_codebase().

    Returns:
        Dict with keys:
            - per_sample: List[Dict] with path + loop_type per file
            - distribution: Dict[str, float] mapping loop_type → percentage
            - total: int total samples classified
    """
    per_sample: List[Dict[str, Any]] = []
    type_counts: Dict[str, int] = {}

    for s in samples:
        lt = classify_loop_type(s["content"])
        per_sample.append({"path": s["path"], "loop_type": lt})
        type_counts[lt] = type_counts.get(lt, 0) + 1

    total = len(samples)
    distribution = {
        lt: round(count / total * 100, 1) if total > 0 else 0.0
        for lt, count in type_counts.items()
    }

    # Ensure all known types are present with 0 if missing
    for lt in ("LINEAR", "FOR_SIMPLE", "FOR_NESTED", "WHILE", "LISTCOMP_ONLY"):
        distribution.setdefault(lt, 0.0)

    logger.info(f"Loop distribution: {distribution}")
    return {
        "per_sample": per_sample,
        "distribution": distribution,
        "total": total,
    }


async def analyze_consistency(
    samples: List[Dict[str, Any]],
    model_a: str,
    model_b: str,
    max_samples: int = 30,
    concurrency: int = 5,
) -> Dict[str, Any]:
    """Run dual-model audit on samples and compute verdict agreement rate.

    For each sample, both model_a and model_b independently audit the code
    using _CALIBRATION_AUDIT_PROMPT. Verdicts are compared to compute the
    agreement rate — the fraction of samples where both models agree (both PASS
    or both FAIL).

    Args:
        samples: List of sample dicts from sample_codebase().
        model_a: First model name (e.g. 'gpt-4o').
        model_b: Second model name (e.g. 'claude-sonnet-4-20250514').
        max_samples: Cap on samples to audit (default 30).
        concurrency: Max concurrent audit calls (default 5).

    Returns:
        Dict with keys:
            - model_a, model_b: model names used
            - agreement_rate: float 0-1
            - total_compared: int number of samples compared
            - details: List[Dict] per-sample results
            - errors: List[str] any errors encountered
    """
    from ..utils.llm_client import LLMClient

    # Cap samples
    audit_samples = samples[:max_samples]
    total = len(audit_samples)
    if total == 0:
        return {
            "model_a": model_a,
            "model_b": model_b,
            "agreement_rate": 1.0,
            "total_compared": 0,
            "details": [],
            "errors": [],
        }

    client_a = LLMClient(model_a)
    client_b = LLMClient(model_b)
    semaphore = asyncio.Semaphore(concurrency)

    errors: List[str] = []
    agreements = 0
    details: List[Dict[str, Any]] = []

    async def audit_one(idx: int, sample: Dict[str, Any]) -> Dict[str, Any]:
        """Audit a single sample with both models concurrently."""
        code = sample["content"]
        prompt = _CALIBRATION_AUDIT_PROMPT.format(code=code[:8000])

        async with semaphore:
            try:
                result_a = await client_a.audit(
                    system_prompt="You are a code reviewer.",
                    audit_input=prompt,
                    temperature=0.1,
                )
                verdict_a = _parse_verdict(result_a.get("content", ""))
            except Exception as e:
                logger.warning(f"Model {model_a} failed on sample {idx}: {e}")
                errors.append(f"Model {model_a} error on sample {idx}: {e}")
                verdict_a = None

            try:
                result_b = await client_b.audit(
                    system_prompt="You are a code reviewer.",
                    audit_input=prompt,
                    temperature=0.1,
                )
                verdict_b = _parse_verdict(result_b.get("content", ""))
            except Exception as e:
                logger.warning(f"Model {model_b} failed on sample {idx}: {e}")
                errors.append(f"Model {model_b} error on sample {idx}: {e}")
                verdict_b = None

        agreed = (verdict_a is not None and verdict_b is not None and verdict_a == verdict_b)
        return {
            "path": sample["path"],
            "verdict_a": verdict_a,
            "verdict_b": verdict_b,
            "agreed": agreed,
        }

    # Run audits with controlled concurrency
    tasks = [audit_one(i, s) for i, s in enumerate(audit_samples)]
    results = await asyncio.gather(*tasks)

    for r in results:
        details.append(r)
        if r["agreed"]:
            agreements += 1

    valid = sum(1 for r in details if r["verdict_a"] is not None and r["verdict_b"] is not None)
    agreement_rate = agreements / valid if valid > 0 else 0.0

    logger.info(
        f"Consistency: {model_a} vs {model_b} → "
        f"{agreements}/{valid} agreed ({agreement_rate:.1%})"
    )

    return {
        "model_a": model_a,
        "model_b": model_b,
        "agreement_rate": round(agreement_rate, 4),
        "total_compared": valid,
        "details": details,
        "errors": errors,
    }


def recommend_pairing(
    consistency_results: Dict[str, Any],
    loop_distribution: Dict[str, float],
) -> Dict[str, Any]:
    """Generate an audit strategy recommendation based on codebase characteristics.

    Single-model sufficient when:
        FOR_NESTED + WHILE + LINEAR > 85%
    Multi-model recommended when:
        LISTCOMP_ONLY > 15% or FOR_SIMPLE > 25%

    Args:
        consistency_results: Output from analyze_consistency().
        loop_distribution: Distribution dict from classify_samples().

    Returns:
        Dict with keys:
            - single_model_sufficient: bool
            - recommended_pair: str | None
            - estimated_api_savings: str
            - rationale: str
    """
    linear = loop_distribution.get("LINEAR", 0)
    for_simple = loop_distribution.get("FOR_SIMPLE", 0)
    for_nested = loop_distribution.get("FOR_NESTED", 0)
    while_pct = loop_distribution.get("WHILE", 0)
    listcomp = loop_distribution.get("LISTCOMP_ONLY", 0)

    single_model_score = linear + for_nested + while_pct
    single_model_sufficient = single_model_score > 85.0

    needs_dual = (listcomp > 15.0) or (for_simple > 25.0)

    agreement = consistency_results.get("agreement_rate", 0)
    model_a = consistency_results.get("model_a", "?")
    model_b = consistency_results.get("model_b", "?")

    # Build rationale
    reasons: List[str] = []

    if single_model_sufficient:
        reasons.append(
            f"Single-model friendly loop types (LINEAR+FOR_NESTED+WHILE) "
            f"dominate at {single_model_score:.1f}% (>85% threshold)"
        )

    if needs_dual:
        reasons_parts = []
        if listcomp > 15.0:
            reasons_parts.append(f"LISTCOMP_ONLY at {listcomp:.1f}% (>15% threshold)")
        if for_simple > 25.0:
            reasons_parts.append(f"FOR_SIMPLE at {for_simple:.1f}% (>25% threshold)")
        reasons.append("Multi-model recommended: " + "; ".join(reasons_parts))

    if agreement >= 0.80:
        reasons.append(
            f"High model agreement ({agreement:.1%}) — dual models add limited value"
        )
    elif agreement < 0.50:
        reasons.append(
            f"Low model agreement ({agreement:.1%}) — dual models provide meaningful divergence"
        )

    # Determine recommendation
    if single_model_sufficient and not needs_dual:
        recommended_pair = None
        estimated_savings = "~50% (single model eliminates second API call)"
    elif not single_model_sufficient or needs_dual:
        recommended_pair = f"{model_a} + {model_b}"
        if agreement > 0.85:
            estimated_savings = "~0-10% (models agree heavily, but loop types require dual)"
        elif agreement < 0.60:
            estimated_savings = "~0% (low agreement — dual models critical for coverage)"
        else:
            estimated_savings = "~20-30% (consider single model for LINEAR files only)"
    else:
        recommended_pair = f"{model_a} + {model_b}"
        estimated_savings = "~30-40% (single model for LINEAR-dominated files)"

    return {
        "single_model_sufficient": single_model_sufficient,
        "recommended_pair": recommended_pair,
        "estimated_api_savings": estimated_savings,
        "rationale": " | ".join(reasons) if reasons else "Insufficient data for recommendation",
    }


def calibrate(
    root_dir: str,
    sample_n: int = 30,
    model_a: str = "gpt-4o",
    model_b: str = "claude-sonnet-4-20250514",
    exts: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Run full calibration pipeline synchronously.

    This is the top-level entry point that orchestrates:
        1. sample_codebase → collect code samples
        2. classify_samples → loop type distribution
        3. analyze_consistency → dual-model verdict agreement
        4. recommend_pairing → final strategy recommendation

    Args:
        root_dir: Root directory of the codebase.
        sample_n: Number of files to sample (default 30).
        model_a: First model name.
        model_b: Second model name.
        exts: File extensions to include (default ['.py']).

    Returns:
        Structured calibration result dict.
    """
    if exts is None:
        exts = [".py"]

    # Phase 1: Sample
    samples = sample_codebase(root_dir, n=sample_n, exts=exts)

    if not samples:
        return {
            "codebase": root_dir,
            "n_files": 0,
            "n_sampled": 0,
            "loop_distribution": {},
            "consistency_scores": {},
            "recommendation": {
                "single_model_sufficient": True,
                "recommended_pair": None,
                "estimated_api_savings": "N/A",
                "rationale": "No code files found in the target directory.",
            },
        }

    # Phase 2: Classify
    classification = classify_samples(samples)
    loop_dist = classification["distribution"]

    # Phase 3: Analyze consistency (async → sync wrapper)
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Already in an async context — create a new loop in a thread?
            # Fall back to a simple synchronous approach via asyncio.run in a subprocess
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    analyze_consistency(samples, model_a, model_b, max_samples=sample_n),
                )
                consistency = future.result(timeout=300)
        else:
            consistency = asyncio.run(
                analyze_consistency(samples, model_a, model_b, max_samples=sample_n)
            )
    except Exception as e:
        logger.error(f"Consistency analysis failed: {e}")
        consistency = {
            "model_a": model_a,
            "model_b": model_b,
            "agreement_rate": 0.0,
            "total_compared": 0,
            "details": [],
            "errors": [str(e)],
        }

    # Phase 4: Recommend
    recommendation = recommend_pairing(consistency, loop_dist)

    return {
        "codebase": root_dir,
        "n_files": classification["total"],
        "n_sampled": len(samples),
        "loop_distribution": loop_dist,
        "consistency_scores": {
            "pair_1": {
                "model_a": model_a,
                "model_b": model_b,
                "agreement_rate": consistency["agreement_rate"],
                "recommended": recommendation["recommended_pair"] is not None,
            },
        },
        "recommendation": recommendation,
    }


def _parse_verdict(text: str) -> Optional[str]:
    """Parse PASS/FAIL verdict from model response text.

    Handles common LLM response variations:
    - Exact "PASS" or "FAIL"
    - Markdown-wrapped like "**PASS**"
    - Leading/trailing whitespace
    - Sentences containing just "PASS" or "FAIL"

    Args:
        text: Raw model response text.

    Returns:
        "PASS", "FAIL", or None if unparseable.
    """
    if not text:
        return None

    upper = text.strip().upper()

    # Direct match
    if upper == "PASS":
        return "PASS"
    if upper == "FAIL":
        return "FAIL"

    # Check first word
    first_word = upper.split()[0] if upper.split() else ""
    if first_word in ("PASS", "FAIL"):
        return first_word

    # Check for word boundary match (handles **PASS**, PASS., etc.)
    import re
    match = re.search(r'\b(PASS|FAIL)\b', upper)
    if match:
        return match.group(1)

    return None
