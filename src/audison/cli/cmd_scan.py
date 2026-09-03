"""CLI 命令：scan — 扫描目录进行维度4（数据完整性）审查。"""

import os
import sys
from pathlib import Path
from typing import List, Tuple

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from ..engine.empirical_verifier import EmpiricalVerifier, VerificationResult
from ..engine.js_empirical_verifier import JSEmpiricalVerifier


# 哈希/缓存相关关键字，用于筛选需要审查的函数
_HASH_KEYWORDS = [
    "hash", "cache", "key", "digest", "hmac",
    "checksum", "fingerprint", "etag",
]


def do_scan(args):
    """扫描目录，运行维度4实证验证。"""
    target = Path(args.path).resolve()
    if not target.exists():
        print(f"错误: 路径不存在 — {target}", file=sys.stderr)
        sys.exit(1)
    if not target.is_dir():
        print(f"错误: 路径不是目录 — {target}", file=sys.stderr)
        sys.exit(1)

    console = Console()
    console.print(Panel.fit(
        f"[bold]Audison Scan[/bold] — 维度4 数据完整性实证验证\n"
        f"目标目录: [cyan]{target}[/cyan]",
        border_style="blue",
    ))

    # 收集文件
    include_js = getattr(args, "js", False)
    extensions = [".py"]
    if include_js:
        extensions.extend([".js", ".ts", ".mjs", ".cjs", ".tsx"])

    files = _collect_files(target, extensions)
    if not files:
        console.print("[yellow]未找到可审查的文件。[/yellow]")
        return

    # 初始化验证器
    py_verifier = EmpiricalVerifier()
    js_verifier = JSEmpiricalVerifier() if include_js else None

    # 执行扫描
    all_results: List[VerificationResult] = []
    scanned_funcs = 0

    for file_path in files:
        file_str = str(file_path)
        ext = file_path.suffix.lower()

        if ext == ".py":
            verifier = py_verifier
        else:
            verifier = js_verifier

        # 快速预扫描：找文件中包含哈希/缓存关键字的函数
        try:
            funcs = _find_hash_related_functions(file_path, ext)
        except Exception:
            continue

        for func_name in funcs:
            scanned_funcs += 1
            result = verifier.verify(file_str, func_name)
            if result.verdict != "UNCERTAIN" or result.uncovered_params:
                all_results.append(result)

    # 汇总
    confirmed = [r for r in all_results if r.verdict == "CONFIRMED"]
    refuted = [r for r in all_results if r.verdict == "REFUTED"]
    uncertain = [r for r in all_results if r.verdict == "UNCERTAIN"]

    # 输出报告
    _render_report(console, target, files, scanned_funcs,
                   confirmed, refuted, uncertain,
                   include_js=include_js)

    # 保存报告
    if getattr(args, "output", None):
        _save_report(args.output, target, files, scanned_funcs,
                     confirmed, refuted, uncertain)
        console.print(f"\n[green]报告已保存到: {args.output}[/green]")


def _collect_files(root: Path, extensions: List[str]) -> List[Path]:
    """递归收集目录下的源文件。"""
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        # 跳过常见忽略目录
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in
                       ("node_modules", "__pycache__", "venv", ".venv",
                        "dist", "build", ".git", "egg-info")]
        for fname in filenames:
            for ext in extensions:
                if fname.endswith(ext):
                    files.append(Path(dirpath) / fname)
                    break
    return sorted(files)


def _find_hash_related_functions(file_path: Path, ext: str) -> List[str]:
    """
    快速预扫描：找到文件中函数名与 hash/cache 关键字相关的函数。

    对于 Python：用 ast 模块解析
    对于 JS/TS：用简单正则，因为只是预筛选
    """
    import re

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []

    keywords_pattern = "|".join(_HASH_KEYWORDS)

    if ext == ".py":
        import ast
        func_names = []
        try:
            tree = ast.parse(content, filename=str(file_path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if re.search(keywords_pattern, node.name, re.IGNORECASE):
                        func_names.append(node.name)
        except SyntaxError:
            return []
        return func_names
    else:
        # JS/TS: regex-based pre-scan
        # Match: function hashFile(...) or const hashFile = (...) => or hashFile(...) {
        func_names = []
        patterns = [
            r'(?:async\s+)?function\s+(\w*(?:' + keywords_pattern + r')\w*)\s*\(',
            r'(?:const|let|var)\s+(\w*(?:' + keywords_pattern + r')\w*)\s*=\s*(?:async\s*)?\(',
            r'(?:const|let|var)\s+(\w*(?:' + keywords_pattern + r')\w*)\s*=\s*(?:async\s+)?function',
            r'(\w*(?:' + keywords_pattern + r')\w*)\s*\(\s*\w+\s*[,)].*\{',
        ]
        seen = set()
        for pat in patterns:
            for match in re.finditer(pat, content, re.IGNORECASE):
                name = match.group(1)
                if name not in seen and not name.startswith("_"):
                    func_names.append(name)
                    seen.add(name)
        return func_names


def _render_report(
    console: Console,
    target: Path,
    files: List[Path],
    scanned_funcs: int,
    confirmed: List[VerificationResult],
    refuted: List[VerificationResult],
    uncertain: List[VerificationResult],
    include_js: bool = False,
):
    """输出彩色终端报告。"""
    # 统计表
    summary = Table(title="扫描摘要", show_header=False, box=None)
    summary.add_column(style="bold")
    summary.add_column()
    summary.add_row("扫描目录", str(target))
    summary.add_row("发现文件", f"{len(files)} 个源文件")
    summary.add_row("审查函数", f"{scanned_funcs} 个")

    lang_label = "Python + JS/TS" if include_js else "Python"
    summary.add_row("语言支持", lang_label)
    console.print(summary)

    # 判定汇总
    stats = Table(title="维度4 判定结果", box=None)
    stats.add_column("判定", style="bold")
    stats.add_column("数量", justify="right")
    stats.add_column("说明", justify="left")
    stats.add_row("[red]CONFIRMED[/red]", str(len(confirmed)),
                   "实证确认：函数参数未被哈希/缓存键完全覆盖 → 真阳性")
    stats.add_row("[green]REFUTED[/green]", str(len(refuted)),
                   "实证驳回：模型声称缺失的参数实际已被覆盖 → 假阳性")
    stats.add_row("[yellow]UNCERTAIN[/yellow]", str(len(uncertain)),
                   "无法判定：缺少足够信息或无法解析 → 需人工复核")
    console.print(stats)

    # CONFIRMED 明细
    if confirmed:
        console.print()
        console.print(Text("CONFIRMED — 实证确认的真阳性", style="bold red"))
        for i, r in enumerate(confirmed[:20], 1):
            console.print(
                f"  {i}. [bold]{r.file_path}:{r.function_name}[/bold] → "
                f"未覆盖 [red]{', '.join(r.uncovered_params)}[/red]"
            )
        if len(confirmed) > 20:
            console.print(f"  ... 还有 {len(confirmed) - 20} 项，使用 --output 保存完整报告")

    # REFUTED 明细
    if refuted:
        console.print()
        console.print(Text("REFUTED — 实证驳回（假阳性过滤）", style="bold green"))
        for i, r in enumerate(refuted[:10], 1):
            console.print(
                f"  {i}. [bold]{r.file_path}:{r.function_name}[/bold] → "
                f"参数 [green]{', '.join(r.hash_key_params)}[/green] 均被覆盖"
            )
        if len(refuted) > 10:
            console.print(f"  ... 还有 {len(refuted) - 10} 项，使用 --output 保存完整报告")

    # 风险评估
    if confirmed:
        risk_level = "HIGH" if len(confirmed) >= 5 else ("MEDIUM" if len(confirmed) >= 2 else "LOW")
        risk_color = "red" if risk_level == "HIGH" else ("yellow" if risk_level == "MEDIUM" else "green")
        console.print()
        console.print(Panel(
            f"发现 [bold {risk_color}]{len(confirmed)} 个[/bold {risk_color}] 实证确认的数据完整性风险\n"
            f"风险等级: [bold {risk_color}]{risk_level}[/bold {risk_color}]\n"
            f"建议: 对 CONFIRMED 案例中的函数进行代码审查，确保哈希/缓存键覆盖所有必要参数。",
            title="风险评估",
            border_style=risk_color,
        ))


def _save_report(
    output_path: str,
    target: Path,
    files: List[Path],
    scanned_funcs: int,
    confirmed: List[VerificationResult],
    refuted: List[VerificationResult],
    uncertain: List[VerificationResult],
):
    """保存完整报告为 Markdown。"""
    lines = [
        f"# Audison Scan Report — 维度4 数据完整性审查",
        f"",
        f"**目标目录**: `{target}`",
        f"**扫描时间**: {__import__('datetime').datetime.now().isoformat()}",
        f"**发现文件**: {len(files)} 个",
        f"**审查函数**: {scanned_funcs} 个",
        f"",
        f"## 汇总",
        f"",
        f"| 判定 | 数量 |",
        f"|------|------|",
        f"| CONFIRMED | {len(confirmed)} |",
        f"| REFUTED | {len(refuted)} |",
        f"| UNCERTAIN | {len(uncertain)} |",
        f"",
    ]

    def _write_section(title: str, results: List[VerificationResult]):
        nonlocal lines
        if not results:
            lines.append(f"## {title}\n\n*（无）*\n")
            return
        lines.append(f"## {title} ({len(results)})")
        lines.append("")
        for r in results:
            lines.append(f"### {r.file_path} → `{r.function_name}()`")
            lines.append(f"")
            lines.append(f"- **判定**: {r.verdict}")
            if r.func_params:
                lines.append(f"- **函数参数**: {', '.join(r.func_params)}")
            if r.hash_key_params:
                lines.append(f"- **哈希覆盖参数**: {', '.join(r.hash_key_params)}")
            if r.uncovered_params:
                lines.append(f"- **未覆盖参数**: {', '.join(r.uncovered_params)}")
            if r.matched_missing:
                lines.append(f"- **匹配声称**: {', '.join(r.matched_missing)}")
            lines.append(f"- **详情**: {r.details}")
            lines.append("")
        lines.append("")

    _write_section("CONFIRMED（实证确认）", confirmed)
    _write_section("REFUTED（实证驳回）", refuted)
    _write_section("UNCERTAIN（待定）", uncertain)

    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
