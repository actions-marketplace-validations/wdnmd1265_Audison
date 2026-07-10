"""
实证验证器 — 维度 4 假阳性过滤器

BrainOpponent 输出维度 4（data_integrity）反例后、TrustReport 生成前，
对每个维度 4 发现进行 AST 层面的真伪验证，判定 CONFIRMED / REFUTED / UNCERTAIN。

核心思路：
- 解析目标 Python 文件的函数定义
- 提取函数签名参数
- 在函数体中定位哈希/缓存键构造调用
- 对比函数参数 vs 哈希键中实际使用的参数
- 输出判定结果
"""

import ast
import os
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

from loguru import logger


@dataclass
class VerificationResult:
    """单个维度 4 反例的验证结果"""
    verdict: str                       # CONFIRMED / REFUTED / UNCERTAIN
    file_path: str
    function_name: str
    func_params: List[str] = field(default_factory=list)
    hash_key_params: List[str] = field(default_factory=list)       # 哈希调用中实际使用的参数
    uncovered_params: List[str] = field(default_factory=list)      # 函数参数中未被哈希覆盖的
    claimed_missing: List[str] = field(default_factory=list)       # 模型声称缺失的字段
    matched_missing: List[str] = field(default_factory=list)       # 确实缺失且与声称匹配的
    unmatched_missing: List[str] = field(default_factory=list)     # 确实缺失但与声称不匹配的
    details: str = ""


class EmpiricalVerifier:
    """
    实证验证器 — 用 AST 静态分析验证维度 4 反例的真实性。

    BrainOpponent 的 LLM 可能产生幻觉（声称某字段缺失但实际上代码已覆盖），
    本验证器在反例进入 TrustReport 前进行代码级验证，过滤假阳性。

    Usage:
        verifier = EmpiricalVerifier()
        result = verifier.verify(
            file_path="/path/to/target.py",
            function_name="hash_file",
            claimed_missing=["content_hash", "version"],
        )
    """

    # 哈希/缓存键相关函数名模式
    _HASH_FUNC_NAMES: Set[str] = {
        "hash", "sha256", "sha1", "md5", "sha512", "sha384",
        "blake2b", "blake2s", "sha3_256", "sha3_512",
        "dumps",  # json.dumps / pickle.dumps / hashlib-like dumps
    }

    # 缓存键构造相关属性/方法
    _KEY_ATTRS: Set[str] = {"hexdigest", "digest", "update"}

    def verify(
        self,
        file_path: str,
        function_name: str,
        claimed_missing: Optional[List[str]] = None,
    ) -> VerificationResult:
        """
        对指定函数进行维度 4 实证验证。

        Args:
            file_path: 目标 Python 源文件绝对路径
            function_name: 要审查的函数名
            claimed_missing: 模型声称的缺失字段列表（可选）

        Returns:
            VerificationResult
        """
        claimed_missing = claimed_missing or []

        if not os.path.isfile(file_path):
            return VerificationResult(
                verdict="UNCERTAIN",
                file_path=file_path,
                function_name=function_name,
                claimed_missing=claimed_missing,
                details=f"文件不存在: {file_path}",
            )

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
        except Exception as e:
            return VerificationResult(
                verdict="UNCERTAIN",
                file_path=file_path,
                function_name=function_name,
                claimed_missing=claimed_missing,
                details=f"无法读取文件: {e}",
            )

        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            return VerificationResult(
                verdict="UNCERTAIN",
                file_path=file_path,
                function_name=function_name,
                claimed_missing=claimed_missing,
                details=f"AST 解析失败 (语法错误): {e}",
            )

        # 定位目标函数
        func_node = self._find_function(tree, function_name)
        if func_node is None:
            return VerificationResult(
                verdict="UNCERTAIN",
                file_path=file_path,
                function_name=function_name,
                claimed_missing=claimed_missing,
                details=f"在文件中未找到函数 '{function_name}'",
            )

        # 提取函数参数
        func_params = self._extract_params(func_node)

        # 在函数体中提取哈希/缓存键调用中使用的参数
        hash_key_params = self._extract_hash_key_params(func_node)

        # 找出未被哈希覆盖的参数
        uncovered = [p for p in func_params if p not in hash_key_params]

        # 与声称缺失字段对比
        matched = [f for f in claimed_missing if f in uncovered]
        unmatched = [f for f in claimed_missing if f not in uncovered and f not in func_params]

        # 判定
        if not uncovered:
            # 所有参数都被哈希覆盖 → 模型声称缺失是假阳性
            verdict = "REFUTED"
            details = (
                f"函数 '{function_name}' 的所有 {len(func_params)} 个参数"
                f"({', '.join(func_params)}) 均已出现在哈希/缓存键构造中。"
                f"模型声称缺失的字段 ({', '.join(claimed_missing)}) 实际已被覆盖，"
                f"该反例为假阳性。"
            )
        elif matched:
            # 部分参数未被覆盖，且与模型声称匹配 → 确认
            verdict = "CONFIRMED"
            details = (
                f"函数 '{function_name}' 接收 {len(func_params)} 个参数"
                f"({', '.join(func_params)})，但哈希/缓存键仅使用了"
                f"({', '.join(hash_key_params) if hash_key_params else '<无>'}）。"
                f"以下参数未被覆盖: {', '.join(uncovered)}。"
                f"其中与模型声称匹配: {', '.join(matched)}。"
                f"该反例被实证确认为真阳性。"
            )
        elif claimed_missing:
            # 有未覆盖参数但与声称不匹配
            verdict = "UNCERTAIN"
            details = (
                f"函数 '{function_name}' 存在未被哈希覆盖的参数"
                f"({', '.join(uncovered)})，但与模型声称缺失的字段"
                f"({', '.join(claimed_missing)}) 不匹配。"
                f"可能是不同层面的问题或模型指代模糊。"
            )
        else:
            # 无声称字段，仅报告现状
            verdict = "UNCERTAIN"
            if uncovered:
                details = (
                    f"函数 '{function_name}' 存在 {len(uncovered)} 个未被哈希覆盖的参数:"
                    f" {', '.join(uncovered)}。但模型未提供具体缺失字段，无法自动判定。"
                )
            else:
                details = (
                    f"函数 '{function_name}' 的所有参数均被哈希覆盖。"
                    f"模型未提供具体缺失字段，无法进一步判定。"
                )

        result = VerificationResult(
            verdict=verdict,
            file_path=file_path,
            function_name=function_name,
            func_params=func_params,
            hash_key_params=hash_key_params,
            uncovered_params=uncovered,
            claimed_missing=claimed_missing,
            matched_missing=matched,
            unmatched_missing=unmatched,
            details=details,
        )

        logger.info(
            f"EmpiricalVerifier: {function_name} → {verdict} | "
            f"params={func_params} | hash_keys={hash_key_params} | "
            f"uncovered={uncovered}"
        )
        return result

    # ── AST 工具方法 ──────────────────────────────────────────

    def _find_function(self, tree: ast.AST, name: str) -> Optional[ast.FunctionDef]:
        """在 AST 中定位指定名称的函数定义（也搜索类方法）。"""
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == name:
                    return node
        return None

    def _extract_params(self, func_node: ast.FunctionDef) -> List[str]:
        """提取函数签名的参数名列表（排除 self/cls）。"""
        params = []
        for arg in func_node.args.args:
            # 跳过 self / cls
            if arg.arg in ("self", "cls"):
                continue
            params.append(arg.arg)

        # 处理 *args, **kwargs
        if func_node.args.vararg:
            params.append(f"*{func_node.args.vararg.arg}")
        if func_node.args.kwarg:
            params.append(f"**{func_node.args.kwarg.arg}")

        return params

    def _extract_hash_key_params(self, func_node: ast.FunctionDef) -> List[str]:
        """
        在函数体中提取哈希/缓存键调用中实际使用的参数名。

        检测模式：
        - hashlib.sha256(param) / hashlib.md5(param)
        - hash(param)
        - json.dumps(dict_with_params)
        - hasher.dumps([a, b, c])
        - obj.update(param)
        - 字典键构造中的参数引用
        """
        used_params: Set[str] = set()
        func_param_names: Set[str] = {
            a.arg for a in func_node.args.args if a.arg not in ("self", "cls")
        }

        class HashKeyVisitor(ast.NodeVisitor):
            def visit_Call(self, node: ast.Call) -> None:
                # 检测哈希相关调用
                if self._is_hash_call(node):
                    # 收集调用参数中引用的函数参数名
                    for arg_node in node.args:
                        used_params.update(self._collect_names(arg_node))
                    for kw in node.keywords:
                        used_params.update(self._collect_names(kw.value))
                self.generic_visit(node)

            def visit_Assign(self, node: ast.Assign) -> None:
                # 检测 dict key 赋值: key = f"{a}_{b}" 或 key = (a, b)
                for target in node.targets:
                    if isinstance(target, ast.Name) and (
                        "key" in target.id.lower()
                        or "cache" in target.id.lower()
                        or "hash" in target.id.lower()
                    ):
                        used_params.update(self._collect_names(node.value))
                self.generic_visit(node)

            def visit_Dict(self, node: ast.Dict) -> None:
                # 字典键中的参数引用
                for key in node.keys:
                    if key is not None:
                        used_params.update(self._collect_names(key))
                self.generic_visit(node)

            @staticmethod
            def _is_hash_call(node: ast.Call) -> bool:
                """判断调用是否为哈希/缓存键构造相关。"""
                # hashlib.xxx()
                if (
                    isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "hashlib"
                ):
                    return True
                # hash()
                if isinstance(node.func, ast.Name) and node.func.id == "hash":
                    return True
                # xxx.dumps() where xxx may be json/pickle/hasher
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"dumps", "hexdigest", "update", "digest"}
                ):
                    return True
                return False

            @staticmethod
            def _collect_names(node: ast.AST) -> Set[str]:
                """递归收集 AST 节点中引用的所有 Name 标识符。"""
                names: Set[str] = set()
                for child in ast.walk(node):
                    if isinstance(child, ast.Name):
                        names.add(child.id)
                    # 也收集 f-string 中的变量
                    elif isinstance(child, ast.FormattedValue):
                        names.update(
                            HashKeyVisitor._collect_names(child.value)
                        )
                return names

        visitor = HashKeyVisitor()
        visitor.visit(func_node)

        # 只保留确实是函数参数的
        return sorted(used_params & func_param_names)

    # ── 便捷方法 ──────────────────────────────────────────────

    def verify_from_finding(
        self,
        file_path: str,
        function_name: str,
        description: str,
    ) -> VerificationResult:
        """
        从反例描述文本中提取 claimed_missing 字段后验证。
        适用于 BrainOpponent 自然语言输出的场景。

        从描述中提取模式如 '缺少 X'、'未包含 Y'、'missing Z' 等。
        """
        import re

        # 提取声称缺失字段的启发式规则
        patterns = [
            r"(?:缺少|缺失|遗漏|未含|未包含|未覆盖|未纳入|忽略)[了]?\s*参数\s*['\"]?(\w+)['\"]?",
            r"(?:缺少|缺失|遗漏|未含|未包含|未覆盖|未纳入|忽略)[了]?\s*['\"]?(\w+)['\"]?",
            r"(?:missing|omitted|lacks|without)\s+['\"]?(\w+)['\"]?",
            r"(?:仅|只)[使用了]?\s*['\"]?(\w+)['\"]?\s*(?:作为|当[作做])",
        ]

        claimed = []
        for pattern in patterns:
            for m in re.finditer(pattern, description, re.IGNORECASE):
                word = m.group(1).strip()
                if word and word not in ("等", "的", "和", "或", "及", "与", "a", "the"):
                    claimed.append(word)

        return self.verify(file_path, function_name, claimed)


# ── 综合入口：批量验证维度 4 反例 ──────────────────────────────

def verify_dimension4_findings(
    findings: List,
    default_file_path: str = "",
    default_function_name: str = "",
) -> List[VerificationResult]:
    """
    对一批 Finding / dict 中类型为 data_integrity 的条目进行批量验证。

    Args:
        findings: Finding 对象列表或 dict 列表
        default_file_path: 无明确文件路径时的默认目标
        default_function_name: 无明确函数名时的默认目标

    Returns:
        验证结果列表（仅含成功触发验证的条目）
    """
    verifier = EmpiricalVerifier()
    results: List[VerificationResult] = []

    for f in findings:
        # 兼容 Finding 对象和 dict
        ftype = getattr(f, "area", "") if hasattr(f, "area") else f.get("type", f.get("area", ""))
        description = getattr(f, "description", "") if hasattr(f, "description") else f.get("description", f.get("scenario", ""))

        if ftype != "data_integrity":
            continue

        # 尝试从 description 中提取 file_path 和 function_name
        file_path = _extract_file_path(description) or default_file_path
        func_name = _extract_function_name(description) or default_function_name

        if not file_path or not func_name:
            logger.debug(f"跳过验证：缺少 file_path 或 function_name | {description[:80]}")
            continue

        result = verifier.verify_from_finding(file_path, func_name, description)
        results.append(result)

    return results


def _extract_file_path(text: str) -> str:
    """从文本中提取文件路径。"""
    import re
    # 匹配常见路径模式（支持 Windows 盘符和 UNC 路径）
    patterns = [
        r"""(?:文件|file|path|in)\s*[:：]?\s*['"]?([\w\-.:/\\]+\.py)['"]?""",
        r"""['"]([\w\-.:/\\]+\.py)['"]""",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return ""


def _extract_function_name(text: str) -> str:
    """从文本中提取函数名。"""
    import re
    patterns = [
        r"""(?:函数|方法|function|method|def)\s*[:：]?\s*['"]?(\w+)['"]?""",
        r"""(\w+)\(\)""",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            name = m.group(1)
            if name not in ("def", "class", "import", "return", "self"):
                return name
    return ""
