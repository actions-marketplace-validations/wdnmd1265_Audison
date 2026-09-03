"""
反对者脑 - 独立第三脑

在 Brain #1 和用户审批之间介入，提供对抗性视角。
"""

import json
import random
from typing import List, Dict, Any, Optional
from loguru import logger

from ..utils.llm_client import LLMClient


class BrainOpponent:
    """
    反对者脑 - 独立第三脑
    
    提供对抗性视角，帮助用户看到方案的潜在问题。
    """
    
    # 风格库
    STYLES = [
        {
            "id": "data_driven",
            "name": "数据派",
            "prompt": "你的假设缺乏数据支撑。请提供用户量、并发数、预算上下限。没有数据的决策是赌博。"
        },
        {
            "id": "minimalist",
            "name": "极简派",
            "prompt": "你为什么需要这个？去掉它系统还能跑吗？如果能，你为什么要增加复杂度？"
        },
        {
            "id": "future_thinker",
            "name": "未来派",
            "prompt": "如果三个月后技术栈完全变了，你现在做的决定还有意义吗？你的方案能适应变化吗？"
        },
        {
            "id": "user_advocate",
            "name": "用户派",
            "prompt": "你的用户真的在乎这个功能吗？还是你自己在乎？你有没有问过他们？"
        },
        {
            "id":         "cost_analyst",
            "name": "成本派",
            "prompt": "这个方案的成本是多少？你有没有考虑过维护成本、学习成本、迁移成本？"
        },
    ]

    # 反例攻防 prompt 模板（结构化审查维度矩阵版）
    ADVERSARIAL_PROMPT = """基于以下任务方案，逐项遍历审查维度矩阵，对每个适用维度尝试生成反例场景。

需求：{description}

执行步骤：
{steps}

═══════════════════════════════════════
审查维度矩阵（必须逐项检查，不可跳过）
═══════════════════════════════════════

维度1 — 输入注入类：检查是否存在 SQL 注入、命令注入、XSS、路径遍历、反序列化、SSRF 等输入处理漏洞。
维度2 — 认证与授权绕过：检查认证逻辑、权限校验、会话管理、JWT 处理是否存在绕过路径或提权可能。
维度3 — 竞态条件与并发缺陷：检查是否存在 TOCTOU、死锁、双重提交、并发写冲突、非原子操作等问题。
维度4 — 数据流与缓存完整性：检查任何数据存储、缓存、索引或哈希操作中，键值/标识符的生成是否覆盖了所有影响数据正确性的必要字段。重点审查函数签名与哈希输入之间的不对称——如果函数接收 N 个参数但哈希/缓存键仅使用了 M 个（N > M），则不同数据可能产生相同键值，导致缓存键冲突、数据覆盖或完整性破坏。典型模式包括：hash(data) 忽略了 metadata（如 sample_rate、format、dtype）；用 fileName 作缓存键但忽略目录路径；序列化时遗漏影响语义的字段。
维度5 — 边界条件与类型安全：检查数值溢出（整数/浮点）、类型混淆、空指针解引用、越界访问、除零、None/undefined 传播等边界问题。
维度6 — 资源管理与泄露：检查文件句柄、数据库连接、网络 socket、内存分配、锁等资源是否正确释放，是否存在泄露路径或未处理的异常分支导致资源未回收。

审查规则：
- 对以上每一个维度进行独立审查，不可合并。
- 如果某维度适用于当前方案，生成 1 个具体反例并标注维度编号。
- 如果某维度不适用于当前方案，将其加入 skipped_dimensions 并注明跳过原因。
- 每个适用维度最多生成 1 个反例。

请严格按照以下 JSON 格式返回（不要包含 markdown 代码块标记）：
{{
  "adversarial_examples": [
    {{
      "dimension": 1,
      "dimension_name": "输入注入类",
      "type": "adversarial_input/exception_flow/edge_condition",
      "scenario": "具体的反例场景描述",
      "expected_break": "该反例预期会暴露方案的什么漏洞",
      "severity": "critical/high/medium"
    }}
  ],
  "skipped_dimensions": [{{"dimension": 4, "reason": "方案不涉及数据缓存或哈希操作"}}],
  "max_rounds": 3
}}

要求：
- 反例要具体、可执行，不是抽象概念
- 每个反例都要明确指出预期暴露的漏洞类型
- 必须逐项遍历全部 6 个维度，不可跳过任何维度
- skipped_dimensions 必须给出明确的原因"""
    
    def __init__(self, model: str = "gpt-4"):
        """
        初始化反对者脑
        
        Args:
            model: 使用的模型
        """
        self.model = model
        self.llm_client = LLMClient(model)
        logger.info(f"反对者脑初始化完成，使用模型: {model}")
    
    async def critique(self, blueprint: Any) -> List[str]:
        """
        对蓝图提出质疑
        
        Args:
            blueprint: 任务蓝图
            
        Returns:
            质疑列表
        """
        # 随机选择一种风格
        style = random.choice(self.STYLES)
        logger.info(f"反对者脑使用风格: {style['name']}")
        
        # 构建系统提示词
        system_prompt = f"""你是一名技术方案评审专家，你的角色是提出质疑和不同角度的思考。

你的风格是：{style['name']}
你的核心观点是：{style['prompt']}

请根据用户的需求和执行方案，提出 2-3 个有深度的质疑点。
质疑应该：
1. 紧贴任务本身
2. 指出潜在的问题或风险
3. 提供不同的思考角度
4. 不要无理抬杠，要有建设性

请直接输出质疑点，每个质疑点一行，不要编号。"""
        
        # 构建用户输入
        steps_desc = "\n".join([
            f"步骤{i+1}: {s.get('name', '')} ({s.get('expert', '')}) - {s.get('task', '')[:80]}"
            for i, s in enumerate(blueprint.steps)
        ])
        
        user_input = f"""需求：{blueprint.description}

执行步骤：
{steps_desc}

请从 {style['name']} 的角度提出质疑。"""
        
        # 调用 LLM
        try:
            response = await self.llm_client.analyze(
                system_prompt=system_prompt,
                user_input=user_input,
                temperature=0.7,
            )
            
            # 解析响应
            critiques = [line.strip() for line in response.split("\n") if line.strip()]
            logger.info(f"反对者脑提出 {len(critiques)} 个质疑")
            return critiques
        except Exception as e:
            logger.warning(f"反对者脑 LLM 调用失败: {e}，使用默认质疑")
            return [
                "这个方案是否过度设计了？",
                "有没有更简单的实现方式？",
                "用户真的需要这些功能吗？",
            ]
    
    def get_available_styles(self) -> List[Dict[str, str]]:
        """
        获取可用的风格列表
        
        Returns:
            风格列表
        """
        return self.STYLES.copy()

    async def generate_adversarial_examples(self, blueprint: Any) -> Dict[str, Any]:
        """
        反例攻防：生成 1-3 个具体反例场景用于压力测试。
        
        Args:
            blueprint: 任务蓝图
            
        Returns:
            反例场景字典，含 adversarial_examples 列表
        """
        steps_desc = "\n".join([
            f"步骤{i+1}: {s.get('name', '')} ({s.get('expert', '')}) - {s.get('task', '')[:80]}"
            for i, s in enumerate(blueprint.steps)
        ])

        TRUNCATION_THRESHOLD = 12000
        truncation_warning: Optional[str] = None
        if len(steps_desc) > TRUNCATION_THRESHOLD:
            original_len = len(steps_desc)
            steps_desc = steps_desc[:TRUNCATION_THRESHOLD]
            truncation_warning = (
                f"[截断警告] 方案步骤过长 ({original_len} → {TRUNCATION_THRESHOLD} 字符)，"
                f"超出部分未送入反对者脑审核，可能存在遗漏！"
            )
            logger.warning(truncation_warning)
        prompt = self.ADVERSARIAL_PROMPT.format(
            description=blueprint.description,
            steps=steps_desc
        )
        
        logger.info(f"反对者脑开始生成反例场景，方案步骤数: {len(blueprint.steps)}")
        
        try:
            response = await self.llm_client.analyze(
                system_prompt="你是一名安全审计专家，你的任务是生成具体的攻击场景来测试方案的鲁棒性。",
                user_input=prompt,
                temperature=0.5,
            )
            # 解析 JSON
            text = response.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:]) if lines[0].startswith("```") else text
                if text.endswith("```"):
                    text = text[:-3]
            result = json.loads(text)
            examples = result.get("adversarial_examples", [])
            logger.info(f"反对者脑生成 {len(examples)} 个反例场景")
            if truncation_warning:
                result["truncation_warning"] = truncation_warning
            return result
        except Exception as e:
            logger.warning(f"反例生成失败: {e}，使用默认反例")
            fallback_examples = [
                {
                    "type": "adversarial_input",
                    "scenario": "用户输入SQL注入payload到登录表单",
                    "expected_break": "未做输入过滤导致数据库被脱库",
                    "severity": "critical"
                },
                {
                    "type": "edge_condition",
                    "scenario": "并发1000个请求同时创建同名用户",
                    "expected_break": "竞态条件导致数据库唯一约束失效",
                    "severity": "high"
                },
                {
                    "type": "data_integrity",
                    "scenario": "缓存键仅使用文件路径作为输入，未包含文件内容哈希或版本号，不同版本的同一路径文件在缓存中互相覆盖",
                    "expected_break": "缓存键冲突导致过期/错误数据被返回，上游消费者基于损坏数据做决策",
                    "severity": "critical"
                },
            ]
            result = {
                "adversarial_examples": fallback_examples,
                "max_rounds": 3,
            }
            if truncation_warning:
                result["truncation_warning"] = truncation_warning
            return result
