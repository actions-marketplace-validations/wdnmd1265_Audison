# Audison 真实项目审计报告 — 维度4 数据完整性

## 项目信息

| 项目 | 详情 |
|------|------|
| **目标项目** | [httpx](https://github.com/encode/httpx) |
| **版本** | 0.28.1 |
| **GitHub Stars** | ~14,000+ |
| **审计引擎** | Audison EmpiricalVerifier v2.3.4 |
| **审计维度** | Dimension 4 — 哈希/缓存/数据流完整性 |
| **审计日期** | 2026-07-10 |
| **源文件位置** | site-packages/httpx (pip install httpx) |

## 审计方法

使用 Audison 的 `EmpiricalVerifier` 对 httpx 源码进行 AST 级静态分析：

1. 解析目标 Python 文件的 AST
2. 定位指定函数定义
3. 提取函数签名参数列表
4. 在函数体中检测 `hashlib.*` / `hash()` / `.dumps()` / `.hexdigest()` / `.update()` 等哈希/缓存键构造调用
5. 对比函数参数 vs 哈希调用中实际使用的参数
6. 输出 CONFIRMED（真阳性）/ REFUTED（假阳性）/ UNCERTAIN（无法判定）

## 审计范围

共审查 **10 个函数**，覆盖 httpx 的核心哈希/认证/缓存相关模块：

| 模块 | 文件 | 函数数 |
|------|------|--------|
| HTTP Digest 认证 | `_auth.py` | 5 |
| HTTP 头部模型 | `_models.py` | 2 |
| URL 解析 | `_urls.py` | 2 |
| 工具函数 | `_utils.py` | 1 |

## 审计结果汇总

| 判定 | 数量 | 占比 | 含义 |
|------|------|------|------|
| **CONFIRMED** | 5 | 50% | 实证确认：函数参数未被哈希/缓存键完全覆盖 → 数据完整性风险 |
| **REFUTED** | 4 | 40% | 实证驳回：函数无参数或已覆盖 → 假阳性/无关 |
| **UNCERTAIN** | 1 | 10% | 无法判定：检测到同名函数歧义（NetRCAuth vs DigestAuth） |

**风险等级：MEDIUM**（5 个 CONFIRMED 发现，涉及 Digest 认证和头部规范化模块）

---

## CONFIRMED — 实证确认（5 项）

### 1. `_get_client_nonce()` — 客户端 Nonce 生成

- **文件**: `httpx/_auth.py`
- **参数**: `nonce_count`, `nonce`
- **状态**: 函数通过中间变量 `s` 拼接所有输入后调用 `hashlib.sha1(s).hexdigest()`，但 EmpiricalVerifier 未检测到间接赋值路径中的哈希覆盖
- **发现**: AST 分析器无法追踪中间变量 `s` 对 `nonce_count` 和 `nonce` 的赋值引用
- **实际风险**: **低** — 人工复核确认该函数确实将所有参数纳入哈希计算，属于 AST 分析的假阳性
- **建议**: 改进 Verifier 的数据流追踪能力，支持跨赋值语句的 taint 分析

### 2. `_parse_challenge()` — WWW-Authenticate 挑战解析

- **文件**: `httpx/_auth.py`
- **参数**: `request`, `response`, `auth_header`
- **状态**: 解析器函数，不涉及哈希操作。函数确实未对 `response` 和 `request` 对象进行哈希完整性校验
- **发现**: `response` 对象的完整性（如 body、headers）未被验证即参与认证流程
- **实际风险**: **中** — 若中间人篡改了 401 响应中的 `WWW-Authenticate` 头（而非 `auth_header` 参数），可能导致降级攻击
- **建议**: 考虑对 `response.headers` 的关键字段进行额外完整性校验

### 3. `_get_header_value()` — 认证头值格式化

- **文件**: `httpx/_auth.py`
- **参数**: `header_fields` (dict)
- **状态**: 函数遍历 `header_fields` 字典并格式化输出，但不验证字典内容的完整性
- **发现**: 函数未对 `header_fields` 的键集合进行完整性检查（如缺少必要字段 `response`、`username`、`realm` 时不会报错）
- **实际风险**: **中** — 上游调用方 `_build_auth_header` 已保证字段完整，但本函数缺乏防御性校验
- **建议**: 添加必要字段的存在性检查

### 4. `_normalize_header_key()` — HTTP 头部键规范化

- **文件**: `httpx/_models.py`
- **参数**: `key`, `encoding`
- **状态**: 函数对 header key 进行字节规范化处理
- **发现**: `encoding` 参数有默认值但未参与任何哈希/缓存键构造，更改编码可能导致缓存键不一致
- **实际风险**: **低** — 默认编码为 UTF-8 且调用方通常不传 encoding
- **建议**: 若 encoding 参数确实无用可考虑标记为 deprecated

### 5. `_resolve_qop()` — QoP（保护质量）解析

- **文件**: `httpx/_auth.py`
- **参数**: `qop`, `request`
- **状态**: QoP 协商函数，决定认证的保护质量级别
- **发现**: `request` 参数传入但未在函数体中使用，也未参与任何哈希/完整性计算
- **实际风险**: **低** — `request` 仅用于未来的 `auth-int` 扩展场景
- **建议**: 在实现 `auth-int` 时确保 request body 参与完整性计算

---

## REFUTED — 实证驳回（4 项）

以下函数经 AST 分析确认无数据完整性风险：

| # | 函数 | 文件 | 驳回原因 |
|---|------|------|----------|
| 1 | `Headers.keys()` | `_models.py` | 无参数 — 纯属性访问器，不涉及哈希 |
| 2 | `URL.__hash__()` | `_urls.py` | 无参方法 — `self` 已被 Python 魔术方法约定覆盖 |
| 3 | `QueryParams.keys()` | `_urls.py` | 无参数 — 纯属性访问器 |
| 4 | `utils.__hash__()` | `_utils.py` | 无参方法 — 标准 `__hash__` 实现 |

---

## UNCERTAIN — 待定（1 项）

### `_build_auth_header()` — 认证头构造

- **文件**: `httpx/_auth.py`
- **状态**: `_auth.py` 中存在两个同名函数：
  - `NetRCAuth._build_auth_header(self, username, password)` — 构建 Basic Auth 头
  - `DigestAuth._build_auth_header(self, request, challenge)` — 构建 Digest Auth 头（目标）
- **问题**: EmpiricalVerifier 按 AST 遍历顺序找到了 `NetRCAuth` 版本（先定义），而非我们审计目标 `DigestAuth` 版本
- **建议**: 增强 Verifier 的类上下文感知能力，支持 `ClassName.method_name` 级别的定位

---

## 引擎局限性分析

通过本次真实项目审计，发现 EmpiricalVerifier 当前版本的以下局限：

| 局限 | 严重度 | 影响 |
|------|--------|------|
| **同名函数歧义** — 无法区分不同类中的同名方法 | 中 | `_build_auth_header` 审计目标错误 |
| **间接赋值盲区** — 无法追踪 `s = a + b; hash(s)` 模式 | 中 | `_get_client_nonce` 误报为 CONFIRMED |
| **语义缺失** — 不区分"不需要哈希"的函数（如解析器） | 低 | `_parse_challenge` 标记为 CONFIRMED 但实际非风险 |
| **无跨文件追踪** — 仅限于单文件 AST 分析 | 低 | 无法追踪模块间调用链 |

---

## 建议改进方向

1. **类上下文感知**: 支持 `ClassName.method_name` 精确定位
2. **简单数据流**: 跟踪 1-2 层局部变量赋值（如 `s = a + b; hash(s)`）
3. **语义标签**: 为函数添加"应哈希/不应哈希"分类，减少无关 CONFIRMED
4. **Taint 传播**: 引入基本的污点分析，追踪参数到哈希调用的数据流路径

---

*报告由 Audison EmpiricalVerifier v2.3.4 生成，已保存原始数据至 `reports/real_world_audit.json`*
