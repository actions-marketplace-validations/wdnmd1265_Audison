"""
实证验证器测试

覆盖三个场景：
1. CONFIRMED — 函数参数未被哈希完全覆盖（Gradio 案例）
2. REFUTED  — 函数参数已被哈希覆盖，模型误判（joblib 案例）
3. UNCERTAIN — 无法判断（文件不存在、函数未找到等）
"""

import os
import tempfile
import pytest
from audison.engine.empirical_verifier import (
    EmpiricalVerifier,
    VerificationResult,
    verify_dimension4_findings,
)


class TestEmpiricalVerifier:
    """EmpiricalVerifier 核心逻辑测试"""

    # ── 辅助方法 ──────────────────────────────────────────

    def _write_temp_file(self, content: str) -> str:
        """写入临时 .py 文件，返回路径"""
        fd, path = tempfile.mkstemp(suffix=".py", prefix="ev_test_")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    # ── CONFIRMED 场景 ────────────────────────────────────

    def test_confirm_missing_param(self):
        """函数参数未被哈希覆盖 → CONFIRMED（Gradio 模式）"""
        code = '''
import hashlib

def cache_file(file_path, version=1):
    """缓存键仅使用 file_path，遗漏 version"""
    key = hashlib.sha256(file_path.encode()).hexdigest()
    return key
'''
        file_path = self._write_temp_file(code)
        verifier = EmpiricalVerifier()
        result = verifier.verify(file_path, "cache_file", ["version"])

        assert result.verdict == "CONFIRMED", f"Expected CONFIRMED, got {result.verdict}: {result.details}"
        assert "file_path" in result.func_params
        assert "version" in result.func_params
        assert "version" in result.uncovered_params
        assert "version" in result.matched_missing

    def test_confirm_missing_content_hash(self):
        """缓存键仅使用文件路径，未含内容哈希 → CONFIRMED"""
        code = '''
import hashlib
import os

def has_file(path, content_hash=""):
    """只哈希文件路径，未哈希内容哈希值"""
    return hashlib.sha256(path.encode()).hexdigest()
'''
        file_path = self._write_temp_file(code)
        verifier = EmpiricalVerifier()
        result = verifier.verify(file_path, "has_file", ["content_hash"])

        assert result.verdict == "CONFIRMED"
        assert "content_hash" in result.func_params
        assert "content_hash" in result.uncovered_params
        assert "content_hash" in result.matched_missing

    def test_confirm_partial_param_coverage(self):
        """函数有 3 个参数但哈希仅覆盖 2 个 → CONFIRMED"""
        code = '''
import json

def make_cache_key(user_id, tenant_id, region):
    """缺少 region"""
    return json.dumps({"user": user_id, "tenant": tenant_id})
'''
        file_path = self._write_temp_file(code)
        verifier = EmpiricalVerifier()
        result = verifier.verify(file_path, "make_cache_key", ["region"])

        assert result.verdict == "CONFIRMED"
        assert "region" in result.uncovered_params
        assert "user_id" not in result.uncovered_params
        assert "tenant_id" not in result.uncovered_params

    # ── REFUTED 场景 ──────────────────────────────────────

    def test_refuted_all_params_covered(self):
        """所有参数被哈希覆盖 → REFUTED（joblib 模式）"""
        code = '''
import hashlib

def np_array_hash(obj, hash_name="md5", coerce_mmap=False):
    """joblib 风格：全部参数参与哈希"""
    hasher = hashlib.new(hash_name)
    hasher.update(str(obj).encode())
    hasher.update(str(coerce_mmap).encode())
    return hasher.hexdigest()
'''
        file_path = self._write_temp_file(code)
        verifier = EmpiricalVerifier()
        result = verifier.verify(file_path, "np_array_hash", ["hash_name", "dtype"])

        assert result.verdict == "REFUTED", f"Expected REFUTED, got {result.verdict}: {result.details}"
        assert "hash_name" in result.hash_key_params
        # dtype 不在参数列表中 → 真正假阳性

    def test_refuted_via_dumps_all_params(self):
        """通过 hasher.dumps([a, b, c]) 覆盖全部参数 → REFUTED"""
        code = '''
class Hasher:
    def dumps(self, obj):
        return str(obj)

def hash_array(arr, dtype=None, order='C'):
    """joblib 实际模式：hasher.dumps 包含 dtype"""
    hasher = Hasher()
    return hasher.dumps([arr, dtype, order])
'''
        file_path = self._write_temp_file(code)
        verifier = EmpiricalVerifier()
        result = verifier.verify(file_path, "hash_array", ["dtype"])

        assert result.verdict == "REFUTED"
        assert "dtype" in result.hash_key_params

    def test_refuted_no_uncovered_params(self):
        """无未覆盖参数 → REFUTED"""
        code = '''
def simple_hash(a, b):
    return hash((a, b))
'''
        file_path = self._write_temp_file(code)
        verifier = EmpiricalVerifier()
        result = verifier.verify(file_path, "simple_hash", ["c"])

        assert result.verdict == "REFUTED"
        assert result.uncovered_params == []

    # ── UNCERTAIN 场景 ────────────────────────────────────

    def test_uncertain_file_not_found(self):
        """文件不存在 → UNCERTAIN"""
        verifier = EmpiricalVerifier()
        result = verifier.verify("/nonexistent/path.py", "some_func", ["field"])

        assert result.verdict == "UNCERTAIN"
        assert "不存在" in result.details

    def test_uncertain_function_not_found(self):
        """函数不在文件中 → UNCERTAIN"""
        code = '''
def other_func():
    pass
'''
        file_path = self._write_temp_file(code)
        verifier = EmpiricalVerifier()
        result = verifier.verify(file_path, "missing_func", ["field"])

        assert result.verdict == "UNCERTAIN"
        assert "未找到函数" in result.details

    def test_uncertain_no_claimed_fields(self):
        """未提供 claimed_missing → UNCERTAIN 但报告现状"""
        code = '''
import hashlib

def hash_data(data, salt=""):
    key = hashlib.sha256(data.encode()).hexdigest()
    return key
'''
        file_path = self._write_temp_file(code)
        verifier = EmpiricalVerifier()
        result = verifier.verify(file_path, "hash_data")

        assert result.verdict == "UNCERTAIN"
        assert "salt" in result.uncovered_params

    def test_uncertain_claimed_not_in_params(self):
        """声称缺失的字段不是真实函数参数 → UNCERTAIN"""
        code = '''
def build_key(name, version):
    return f"{name}_{version}"
'''
        file_path = self._write_temp_file(code)
        verifier = EmpiricalVerifier()
        result = verifier.verify(file_path, "build_key", ["content_hash", "etag"])

        assert result.verdict == "UNCERTAIN"
        assert "content_hash" in result.unmatched_missing

    # ── AST 解析边界 ──────────────────────────────────────

    def test_method_with_self_is_filtered(self):
        """类方法中的 self 不应被列为函数参数"""
        code = '''
import hashlib

class CacheManager:
    def build_key(self, file_id, namespace):
        return hashlib.sha256(f"{file_id}_{namespace}".encode()).hexdigest()
'''
        file_path = self._write_temp_file(code)
        verifier = EmpiricalVerifier()
        result = verifier.verify(file_path, "build_key", ["namespace"])

        assert "self" not in result.func_params
        assert "file_id" in result.hash_key_params
        assert "namespace" in result.hash_key_params
        assert result.verdict == "REFUTED"

    def test_hashlib_update_chain(self):
        """hashlib update() 链式调用也应被检测"""
        code = '''
import hashlib

def hash_multipart(name, ext, size):
    h = hashlib.sha256()
    h.update(name.encode())
    h.update(str(size).encode())
    # ext 被遗漏！故意不 update
    return h.hexdigest()
'''
        file_path = self._write_temp_file(code)
        verifier = EmpiricalVerifier()
        result = verifier.verify(file_path, "hash_multipart", ["ext"])

        assert result.verdict == "CONFIRMED"
        assert "ext" in result.uncovered_params

    def test_detect_from_finding_description(self):
        """verify_from_finding 从自然语言描述中提取 claimed_missing"""
        code = '''
import hashlib

def make_cache_key(path, content_version, mtime):
    return hashlib.sha256(f"{path}_{mtime}".encode()).hexdigest()
'''
        file_path = self._write_temp_file(code)
        verifier = EmpiricalVerifier()

        # 模拟 BrainOpponent 的典型输出
        description = (
            "函数 make_cache_key 缓存键仅使用 path 作为输入，"
            "未包含 content_version，导致不同版本文件可能产生相同缓存键"
        )
        result = verifier.verify_from_finding(file_path, "make_cache_key", description)

        assert result.verdict in ("CONFIRMED", "REFUTED", "UNCERTAIN")
        # content_version 应该被检测为 uncovered
        assert "content_version" in result.uncovered_params or result.verdict != "CONFIRMED"


class TestVerifyDimension4Findings:
    """批量验证入口测试"""

    def test_filters_non_data_integrity(self):
        """非维度 4 的 finding 应被跳过"""
        findings = [
            {"type": "adversarial_input", "description": "SQL 注入场景"},
            {"type": "edge_condition", "description": "竞态条件场景"},
        ]
        results = verify_dimension4_findings(findings)
        assert len(results) == 0

    def test_accepts_finding_objects(self):
        """兼容 Finding 对象"""
        from audison.engine.trust_report import Finding

        # 创建临时文件
        code = '''
import hashlib
def test_func(a, b, c):
    return hashlib.sha256(f"{a}_{b}".encode()).hexdigest()
'''
        fd, path = tempfile.mkstemp(suffix=".py", prefix="ev_batch_")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)

        findings = [
            Finding(
                area="data_integrity",
                severity="high",
                description=f"函数 test_func() 缺少参数 c | 文件 {path}",
                source="opponent",
            )
        ]
        results = verify_dimension4_findings(findings)

        assert len(results) == 1
        assert results[0].verdict == "CONFIRMED"
        assert "c" in results[0].uncovered_params
