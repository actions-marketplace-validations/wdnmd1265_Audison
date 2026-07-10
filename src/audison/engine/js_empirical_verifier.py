"""
JavaScript/TypeScript 实证验证器 — 维度 4 假阳性过滤器

为 JS/TS 代码提供与 Python EmpiricalVerifier 相同的验证接口：
输入目标函数 → 对比函数签名参数数 vs 哈希调用中实际使用的参数数 → CONFIRMED / REFUTED / UNCERTAIN。

依赖 tree-sitter 进行可靠的 AST 解析（不使用正则），
检测的哈希模式包括：
- crypto.createHash("sha256").update(data).digest("hex")
- new Hasher().update(data)
- createHash("md5").update(a).update(b)
- hash(data) 的通用调用
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional, Set

from loguru import logger

# ============================================================
# 与 Python EmpiricalVerifier 共用数据结构
# ============================================================
from .empirical_verifier import VerificationResult


class JSEmpiricalVerifier:
    """
    JS/TS 实证验证器 — 用 tree-sitter AST 静态分析验证维度 4 反例。

    BrainOpponent 的 LLM 输出声称某 JS/TS 函数遗漏哈希字段时，
    本验证器解析 JS/TS AST，定位函数中的哈希构造调用并收集已使用的参数，
    最后与函数签名对比，输出 CONFIRMED / REFUTED / UNCERTAIN。

    Usage (same as EmpiricalVerifier):
        verifier = JSEmpiricalVerifier()
        result = verifier.verify(
            file_path="/path/to/target.js",
            function_name="hashFile",
            claimed_missing=["contentHash", "version"],
        )
    """

    # ── 哈希相关函数名/属性名模式 ──
    _HASH_CONSTRUCTOR_FNS: Set[str] = {
        "createHash", "createHmac", "scrypt", "scryptSync",
        "pbkdf2", "pbkdf2Sync",
    }

    _HASH_UPDATE_ATTRS: Set[str] = {"update", "write"}

    _HASH_FINALIZE_ATTRS: Set[str] = {"digest", "hexdigest", "final"}

    _GENERIC_HASH_FNS: Set[str] = {"hash"}

    def __init__(self):
        """初始化 tree-sitter 解析器。"""
        self._js_parser = None
        self._ts_parser = None
        self._lazy_init_done = False

    def _lazy_init(self):
        """延迟加载 tree-sitter 语言（避免无 tree-sitter 环境崩溃）。"""
        if self._lazy_init_done:
            return
        try:
            import tree_sitter
            import tree_sitter_javascript as tsjs
            import tree_sitter_typescript as tsts

            js_lang = tree_sitter.Language(tsjs.language())
            self._js_parser = tree_sitter.Parser(js_lang)

            ts_lang = tree_sitter.Language(tsts.language_typescript())
            self._ts_parser = tree_sitter.Parser(ts_lang)
        except ImportError as e:
            logger.warning(f"tree-sitter 未安装，JS/TS 验证器不可用: {e}")
        self._lazy_init_done = True

    def verify(
        self,
        file_path: str,
        function_name: str,
        claimed_missing: Optional[List[str]] = None,
    ) -> VerificationResult:
        """
        对指定 JS/TS 函数进行维度 4 实证验证。

        Args:
            file_path: 目标源文件绝对路径 (.js / .ts / .mjs / .cjs)
            function_name: 要审查的函数名
            claimed_missing: 模型声称的缺失字段列表

        Returns:
            VerificationResult（复用 Python 版本的数据结构）
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

        self._lazy_init()

        if self._js_parser is None and self._ts_parser is None:
            return VerificationResult(
                verdict="UNCERTAIN",
                file_path=file_path,
                function_name=function_name,
                claimed_missing=claimed_missing,
                details="tree-sitter 不可用，无法解析 JS/TS 文件",
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

        # 根据扩展名选择解析器
        ext = os.path.splitext(file_path)[1].lower()
        is_ts = ext in (".ts", ".tsx", ".mts", ".cts")
        parser = (self._ts_parser if is_ts else self._js_parser)
        if parser is None:
            # 回退：有哪种用哪种
            parser = self._ts_parser or self._js_parser
        if parser is None:
            return VerificationResult(
                verdict="UNCERTAIN",
                file_path=file_path,
                function_name=function_name,
                claimed_missing=claimed_missing,
                details="无可用解析器",
            )

        try:
            tree = parser.parse(source.encode("utf-8"))
        except Exception as e:
            return VerificationResult(
                verdict="UNCERTAIN",
                file_path=file_path,
                function_name=function_name,
                claimed_missing=claimed_missing,
                details=f"AST 解析失败: {e}",
            )

        # 定位函数节点
        func_node = self._find_function(tree.root_node, function_name)
        if func_node is None:
            return VerificationResult(
                verdict="UNCERTAIN",
                file_path=file_path,
                function_name=function_name,
                claimed_missing=claimed_missing,
                details=f"在文件中未找到函数 '{function_name}'",
            )

        # 提取参数
        func_params = self._extract_params(func_node)

        # 收集哈希调用中使用的参数
        hash_key_params = self._extract_hash_key_params(func_node, func_params)

        # 找出未被哈希覆盖的参数
        uncovered = [p for p in func_params if p not in hash_key_params]

        # 与声称缺失字段对比
        matched = [f for f in claimed_missing if f in uncovered]
        unmatched = [f for f in claimed_missing if f not in uncovered and f not in func_params]

        # 判定
        if not uncovered:
            verdict = "REFUTED"
            details = (
                f"函数 '{function_name}' 的所有 {len(func_params)} 个参数"
                f"({', '.join(func_params)}) 均已出现在哈希/缓存键构造中。"
                f"模型声称缺失的字段 ({', '.join(claimed_missing)}) 实际已被覆盖，"
                f"该反例为假阳性。"
            )
        elif matched:
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
            verdict = "UNCERTAIN"
            details = (
                f"函数 '{function_name}' 存在未被哈希覆盖的参数"
                f"({', '.join(uncovered)})，但与模型声称缺失的字段"
                f"({', '.join(claimed_missing)}) 不匹配。"
            )
        else:
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
            f"JSEmpiricalVerifier: {function_name} → {verdict} | "
            f"params={func_params} | hash_keys={hash_key_params} | "
            f"uncovered={uncovered}"
        )
        return result

    # ── AST 导航方法 ──────────────────────────────────────

    def _find_function(self, root_node, name: str):
        """在 JS/TS AST 中定位指定名称的函数（包括 function / method / arrow）。"""
        for node in _walk_all(root_node):
            if node.type == "function_declaration":
                child = node.child_by_field_name("name")
                if child and _text_of(child) == name:
                    # TS: function_declaration 内部有 identifier
                    return node
            elif node.type == "method_definition":
                child = node.child_by_field_name("name")
                if child and _text_of(child) == name:
                    return node
            # 变量赋值函数: const hashFile = function(...) {}
            elif node.type == "variable_declarator":
                id_node = node.child_by_field_name("name")
                if id_node and _text_of(id_node) == name:
                    value = node.child_by_field_name("value")
                    if value and value.type in ("function_expression", "arrow_function"):
                        return value
        return None

    def _extract_params(self, func_node) -> List[str]:
        """提取 JS/TS 函数签名的参数名（跳过 'this' 但保留其余）。"""
        params = []
        params_node = func_node.child_by_field_name("parameters")
        if params_node is None:
            return params
        for child in params_node.named_children:
            if child.type == "identifier":
                params.append(_text_of(child))
            elif child.type in ("required_parameter", "optional_parameter"):
                # TS: required_parameter has no "name" field;
                # the identifier is a direct child
                id_node = (child.child_by_field_name("name") or
                           _find_child_of_type(child, "identifier"))
                if id_node:
                    name = _text_of(id_node)
                    if name != "this":
                        params.append(name)
            elif child.type == "rest_pattern":
                id_node = child.child_by_field_name("value")
                if id_node:
                    params.append(f"...{_text_of(id_node)}")
        return params

    def _extract_hash_key_params(self, func_node, func_param_names: List[str]) -> List[str]:
        """
        遍历函数体，收集哈希/缓存键调用中引用的函数参数名。

        检测模式：
        1. crypto.createHash("md5").update(x).digest("hex") 链式调用
        2. const h = crypto.createHash("sha256"); h.update(a); h.update(b);
        3. new Hasher().update(x)
        4. hash(x) 通用调用
        """
        func_param_set = set(func_param_names)
        used_params: Set[str] = set()

        # 第一遍：找到所有哈希对象变量名
        hash_object_vars: Set[str] = self._find_hash_object_vars(func_node)

        body = func_node.child_by_field_name("body")
        if body is None:
            return []

        for node in _walk_all(body):
            if node.type == "call_expression":
                used = self._collect_params_from_call(
                    node, func_param_set, hash_object_vars
                )
                used_params.update(used)

        return sorted(used_params & func_param_set)

    def _find_hash_object_vars(self, func_node) -> Set[str]:
        """找到函数体内赋值为哈希对象的变量名（如 'const h = crypto.createHash(...)'）。"""
        hash_vars: Set[str] = set()
        body = func_node.child_by_field_name("body")
        if body is None:
            return hash_vars

        for node in _walk_all(body):
            # variable_declarator: name = value
            if node.type == "variable_declarator":
                value = node.child_by_field_name("value")
                if value is None:
                    continue
                if self._is_hash_constructor(value):
                    id_node = node.child_by_field_name("name")
                    if id_node:
                        hash_vars.add(_text_of(id_node))

            # assignment: left = right
            elif node.type == "assignment_expression":
                left = node.child_by_field_name("left")
                right = node.child_by_field_name("right")
                if left and right and self._is_hash_constructor(right):
                    hash_vars.add(_text_of(left))

            # new Hasher() — the call_expression inside new_expression
            elif node.type == "new_expression":
                constructor = node.child_by_field_name("constructor")
                if constructor:
                    # Walk up to find the variable being assigned
                    parent = node.parent
                    if parent and parent.type == "variable_declarator":
                        id_node = parent.child_by_field_name("name")
                        if id_node:
                            name = _text_of(id_node)
                            ctor_name = _text_of(constructor).lower() if constructor else ""
                            if ctor_name in ("hasher", "hash", "crypto"):
                                hash_vars.add(name)

        return hash_vars

    def _is_hash_constructor(self, node) -> bool:
        """判断节点是否为哈希对象构造函数调用。"""
        if node.type != "call_expression":
            return False
        fn = node.child_by_field_name("function")
        if fn is None:
            return False

        # new Hasher() / new crypto.Hash()
        if node.type == "new_expression":
            fn = node.child_by_field_name("constructor")
            if fn and fn.type == "identifier":
                return fn.text and fn.text.decode().lower() in ("hasher", "hash")

        fn_text = _text_of(fn)

        # crypto.createHash / crypto.createHmac
        if fn.type == "member_expression":
            obj = fn.child_by_field_name("object")
            prop = fn.child_by_field_name("property")
            if obj and prop:
                obj_text = _text_of(obj)
                prop_text = _text_of(prop)
                # crypto.createHash, require('crypto').createHash
                if prop_text in self._HASH_CONSTRUCTOR_FNS:
                    return True
                # Any object .createHash / .createHmac
                if (obj_text.lower() in ("crypto", "require") or
                        prop_text in self._HASH_CONSTRUCTOR_FNS):
                    return True

        # Simple: createHash("md5")
        if fn.type == "identifier" and fn_text in self._HASH_CONSTRUCTOR_FNS:
            return True

        return False

    def _collect_params_from_call(
        self, node, func_param_set: Set[str], hash_object_vars: Set[str]
    ) -> Set[str]:
        """
        从一个 call_expression 节点中收集引用的函数参数名。

        满足以下条件之一才收集：
        - 调用的是 crypto.createHash()、hash()、xxx.digest() 等哈希相关方法
        - 调用的是已知哈希对象变量的 .update() 方法
        - 链式 .update() 调用（如 hash.create().update(a).update(b)）
        """
        used: Set[str] = set()
        fn = node.child_by_field_name("function")
        if fn is None:
            return used

        should_collect = False

        if fn.type == "member_expression":
            prop = fn.child_by_field_name("property")
            obj = fn.child_by_field_name("object")
            prop_text = _text_of(prop) if prop else ""

            # .update() / .write() — detect on hash objects or in chains
            if prop_text in self._HASH_UPDATE_ATTRS:
                if obj:
                    obj_text = _text_of(obj)
                    if obj_text in hash_object_vars:
                        should_collect = True
                    elif obj.type == "call_expression":
                        if self._is_hash_constructor(obj):
                            should_collect = True
                        # Chained: .update(a).update(b) — the obj itself is an update call
                        elif obj.child_by_field_name("function") is not None:
                            obj_fn = obj.child_by_field_name("function")
                            if obj_fn and obj_fn.type == "member_expression":
                                obj_prop = obj_fn.child_by_field_name("property")
                                obj_prop_text = _text_of(obj_prop) if obj_prop else ""
                                if obj_prop_text in self._HASH_UPDATE_ATTRS:
                                    should_collect = True

            # .digest() — collect args if part of chain
            elif prop_text in self._HASH_FINALIZE_ATTRS:
                if obj and obj.type == "call_expression":
                    inner_fn = obj.child_by_field_name("function")
                    if inner_fn and inner_fn.type == "member_expression":
                        inner_prop = inner_fn.child_by_field_name("property")
                        inner_prop_text = _text_of(inner_prop) if inner_prop else ""
                        if inner_prop_text in self._HASH_UPDATE_ATTRS:
                            should_collect = True

            # createHash / createHmac — collect constructor args
            if prop_text in self._HASH_CONSTRUCTOR_FNS:
                should_collect = True

        elif fn.type == "identifier":
            fn_text = _text_of(fn)
            if fn_text in self._GENERIC_HASH_FNS:
                should_collect = True
            if fn_text in self._HASH_CONSTRUCTOR_FNS:
                should_collect = True

        if should_collect:
            args = node.child_by_field_name("arguments")
            if args:
                for arg in args.named_children:
                    names = _collect_identifiers(arg)
                    used.update(names & func_param_set)

        # 递归收集链式调用中的参数
        # e.g., crypto.createHash("sha256").update(data) → 收集 data
        if fn.type == "member_expression":
            obj = fn.child_by_field_name("object")
            if obj and obj.type == "call_expression":
                if self._is_hash_constructor(obj):
                    args = obj.child_by_field_name("arguments")
                    if args:
                        for arg in args.named_children:
                            names = _collect_identifiers(arg)
                            used.update(names & func_param_set)
                # Also check if obj is a chained .update() call
                elif obj.child_by_field_name("function") is not None:
                    obj_fn = obj.child_by_field_name("function")
                    if obj_fn and obj_fn.type == "member_expression":
                        obj_prop = obj_fn.child_by_field_name("property")
                        obj_prop_text = _text_of(obj_prop) if obj_prop else ""
                        if obj_prop_text in self._HASH_UPDATE_ATTRS:
                            args = obj.child_by_field_name("arguments")
                            if args:
                                for arg in args.named_children:
                                    names = _collect_identifiers(arg)
                                    used.update(names & func_param_set)

        return used


# ============================================================
# 通用 AST 工具函数
# ============================================================

def _walk_all(node):
    """递归遍历 tree-sitter AST 节点（含自身）。"""
    yield node
    for child in node.children:
        yield from _walk_all(child)


def _text_of(node) -> str:
    """获取节点的源码文本，解码为 UTF-8 字符串。"""
    if node is None:
        return ""
    text = node.text
    if text is None:
        return ""
    if isinstance(text, bytes):
        return text.decode("utf-8", errors="replace")
    return text


def _find_child_of_type(node, target_type: str):
    """在 node 的直接子节点中查找第一个指定类型的节点。"""
    for child in node.children:
        if child.type == target_type:
            return child
    return None


def _collect_identifiers(node) -> Set[str]:
    """递归收集 AST 子树中所有 identifier 节点的名称。"""
    names: Set[str] = set()
    for child in _walk_all(node):
        if child.type == "identifier":
            names.add(_text_of(child))
    return names
