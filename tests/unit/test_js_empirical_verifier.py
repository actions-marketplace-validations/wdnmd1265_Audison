"""
JS/TS 实证验证器测试

覆盖三个判定场景：
1. CONFIRMED — 函数参数未被哈希完全覆盖
2. REFUTED  — 函数参数已被哈希覆盖，模型误判
3. UNCERTAIN — 无法判断（文件不存在、函数未找到、tree-sitter 不可用等）
"""

import os
import tempfile
import pytest

from audison.engine.js_empirical_verifier import JSEmpiricalVerifier


class TestJSEmpiricalVerifier:
    """JSEmpiricalVerifier 核心逻辑测试"""

    @staticmethod
    def _write_temp_file(content: str, suffix: str = ".js") -> str:
        """写入临时文件，返回路径"""
        fd, path = tempfile.mkstemp(suffix=suffix, prefix="js_ev_test_")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    # ── CONFIRMED 场景 ────────────────────────────────────

    def test_confirm_missing_param_crypto_createhash(self):
        """crypto.createHash 仅使用部分参数 → CONFIRMED"""
        code = """
const crypto = require('crypto');

function hashFile(filePath, version) {
    // 仅哈希 filePath，遗漏 version
    return crypto.createHash("sha256").update(filePath).digest("hex");
}
"""
        file_path = self._write_temp_file(code)
        verifier = JSEmpiricalVerifier()
        result = verifier.verify(file_path, "hashFile", ["version"])

        assert result.verdict == "CONFIRMED", (
            f"Expected CONFIRMED, got {result.verdict}: {result.details}"
        )
        assert "filePath" in result.func_params
        assert "version" in result.func_params
        assert "version" in result.uncovered_params
        assert "version" in result.matched_missing

    def test_confirm_partial_params_hasher_update(self):
        """new Hasher().update() 仅覆盖部分参数 → CONFIRMED"""
        code = """
class Hasher {
    update(data) { this.data = data; return this; }
    digest() { return this.data; }
}

function buildCacheKey(userId, tenantId, region) {
    const h = new Hasher();
    h.update(userId);
    h.update(tenantId);
    // region 遗漏
    return h.digest();
}
"""
        file_path = self._write_temp_file(code)
        verifier = JSEmpiricalVerifier()
        result = verifier.verify(file_path, "buildCacheKey", ["region"])

        assert result.verdict == "CONFIRMED", (
            f"Expected CONFIRMED, got {result.verdict}: {result.details}"
        )
        assert "region" in result.uncovered_params
        assert "userId" not in result.uncovered_params
        assert "tenantId" not in result.uncovered_params

    def test_confirm_generic_hash_only_one_param(self):
        """通用 hash() 调用仅覆盖一个参数 → CONFIRMED"""
        code = """
function makeKey(name, version, namespace) {
    // hash() 只用了 name + version，漏了 namespace
    return hash(name + "_" + version);
}
"""
        file_path = self._write_temp_file(code)
        verifier = JSEmpiricalVerifier()
        result = verifier.verify(file_path, "makeKey", ["namespace"])

        assert result.verdict == "CONFIRMED"
        assert "namespace" in result.uncovered_params

    def test_confirm_arrow_function(self):
        """箭头函数中哈希遗漏参数 → CONFIRMED"""
        code = """
const crypto = require('crypto');

const cacheKey = (data, salt, timestamp) => {
    // 仅使用 data，遗漏 salt 和 timestamp
    return crypto.createHash("md5").update(data).digest("hex");
};
"""
        file_path = self._write_temp_file(code)
        verifier = JSEmpiricalVerifier()
        result = verifier.verify(file_path, "cacheKey", ["salt", "timestamp"])

        assert result.verdict == "CONFIRMED"
        assert "salt" in result.uncovered_params
        assert "timestamp" in result.uncovered_params
        assert "data" not in result.uncovered_params

    # ── REFUTED 场景 ──────────────────────────────────────

    def test_refuted_all_params_covered_via_update_chain(self):
        """所有参数通过 .update() 链覆盖 → REFUTED"""
        code = """
const crypto = require('crypto');

function hashParts(name, ext, size) {
    const h = crypto.createHash("sha256");
    h.update(name);
    h.update(ext);
    h.update(String(size));
    return h.digest("hex");
}
"""
        file_path = self._write_temp_file(code)
        verifier = JSEmpiricalVerifier()
        result = verifier.verify(file_path, "hashParts", ["ext"])

        assert result.verdict == "REFUTED", (
            f"Expected REFUTED, got {result.verdict}: {result.details}"
        )
        assert "ext" in result.hash_key_params

    def test_refuted_via_chained_update(self):
        """链式 .update() 覆盖所有参数 → REFUTED"""
        code = """
const crypto = require('crypto');

function hashConfig(configId, configVersion) {
    return crypto.createHash("sha256")
        .update(configId)
        .update(configVersion)
        .digest("hex");
}
"""
        file_path = self._write_temp_file(code)
        verifier = JSEmpiricalVerifier()
        result = verifier.verify(file_path, "hashConfig", ["configId", "configVersion"])

        assert result.verdict == "REFUTED"
        assert "configId" in result.hash_key_params
        assert "configVersion" in result.hash_key_params

    def test_refuted_class_method_all_params(self):
        """类方法中所有参数均被哈希覆盖 → REFUTED"""
        code = """
const crypto = require('crypto');

class CacheService {
    buildKey(fileId, namespace) {
        const h = crypto.createHash("md5");
        h.update(fileId);
        h.update(namespace);
        return h.digest("hex");
    }
}
"""
        file_path = self._write_temp_file(code)
        verifier = JSEmpiricalVerifier()
        result = verifier.verify(file_path, "buildKey", ["fileId"])

        assert result.verdict == "REFUTED"
        assert result.uncovered_params == []

    def test_refuted_no_uncovered_params(self):
        """无未覆盖参数，声称字段不在参数列表中（真·假阳性）→ REFUTED"""
        code = """
function simpleHash(a, b) {
    const h = require('crypto').createHash('sha1');
    h.update(a);
    h.update(b);
    return h.digest('hex');
}
"""
        file_path = self._write_temp_file(code)
        verifier = JSEmpiricalVerifier()
        result = verifier.verify(file_path, "simpleHash", ["c", "d"])

        assert result.verdict == "REFUTED"
        assert result.uncovered_params == []

    # ── UNCERTAIN 场景 ────────────────────────────────────

    def test_uncertain_file_not_found(self):
        """文件不存在 → UNCERTAIN"""
        verifier = JSEmpiricalVerifier()
        result = verifier.verify("/nonexistent/file.js", "someFunc", ["field"])
        assert result.verdict == "UNCERTAIN"
        assert "不存在" in result.details

    def test_uncertain_function_not_found(self):
        """函数不在文件中 → UNCERTAIN"""
        code = "function otherFunc() { return 1; }"
        file_path = self._write_temp_file(code)
        verifier = JSEmpiricalVerifier()
        result = verifier.verify(file_path, "missingFunc", ["field"])
        assert result.verdict == "UNCERTAIN"
        assert "未找到函数" in result.details

    def test_uncertain_no_claimed_fields(self):
        """未提供 claimed_missing → UNCERTAIN 但报告现状"""
        code = """
const crypto = require('crypto');

function hashData(data, salt) {
    // 遗漏 salt
    return crypto.createHash("sha256").update(data).digest("hex");
}
"""
        file_path = self._write_temp_file(code)
        verifier = JSEmpiricalVerifier()
        result = verifier.verify(file_path, "hashData")

        assert result.verdict == "UNCERTAIN"
        assert "salt" in result.uncovered_params

    # ── TypeScript 测试 ───────────────────────────────────

    def test_ts_confirm_missing_param(self):
        """TypeScript 函数：类型注解，哈希遗漏参数 → CONFIRMED"""
        code = """
import * as crypto from 'crypto';

function hashFile(filePath: string, version: number): string {
    return crypto.createHash("sha256").update(filePath).digest("hex");
}
"""
        file_path = self._write_temp_file(code, suffix=".ts")
        verifier = JSEmpiricalVerifier()
        result = verifier.verify(file_path, "hashFile", ["version"])

        assert result.verdict == "CONFIRMED"
        assert "version" in result.func_params
        assert "version" in result.uncovered_params

    def test_ts_refuted_all_covered(self):
        """TS 函数：类型注解 + 全参数覆盖 → REFUTED"""
        code = """
import * as crypto from 'crypto';

function makeHash(name: string, timestamp: number): string {
    const h = crypto.createHash("sha1");
    h.update(name);
    h.update(String(timestamp));
    return h.digest("hex");
}
"""
        file_path = self._write_temp_file(code, suffix=".ts")
        verifier = JSEmpiricalVerifier()
        result = verifier.verify(file_path, "makeHash", ["timestamp"])

        assert result.verdict == "REFUTED"
        assert "timestamp" in result.hash_key_params

    # ── 边界场景 ──────────────────────────────────────────

    def test_exported_function(self):
        """export function → 应能正常解析"""
        code = """
const crypto = require('crypto');

function hashExport(path, meta) {
    return crypto.createHash("sha256").update(path).digest("hex");
}

module.exports = { hashExport };
"""
        file_path = self._write_temp_file(code)
        verifier = JSEmpiricalVerifier()
        result = verifier.verify(file_path, "hashExport", ["meta"])

        assert result.verdict == "CONFIRMED"
        assert "meta" in result.uncovered_params
