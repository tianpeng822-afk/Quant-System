import os
import json
from loguru import logger
from openai import OpenAI
from app.config import settings

def call_deepseek_diagnose(fund_name: str, fund_code: str, drawdown: float, top_funds: list) -> str:
    """
    调用 DeepSeek API 进行持仓诊断和换基建议
    """
    if not settings.DEEPSEEK_API_KEY:
        logger.warning("DeepSeek API Key 未配置，无法进行 AI 诊断")
        return "⚠️ 系统未配置 DEEPSEEK_API_KEY，AI 诊断服务不可用。"

    client = OpenAI(
        api_key=settings.DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )

    # 构造同类优质基金的参考数据字符串
    top_funds_str = "\n".join([
        f"- {f['基金简称']}({f['基金代码']})：近1年收益 {f.get('近1年', 'N/A')}%，近3年收益 {f.get('近3年', 'N/A')}%"
        for f in top_funds[:5]
    ])

    # 动态构建 Prompt，根据真实回撤情况调整语境
    if drawdown < -10.0:
        situation = f"目前最大回撤已达到 {drawdown:.2f}%，处于深度亏损/回撤状态，可能触发了止损预警。"
        action_req = "简要分析目前该基金可能跌跌不休的宏观/行业原因，并给出明确的建议（死扛、减仓、还是立刻转换）。"
    elif drawdown < -5.0:
        situation = f"目前最大回撤为 {drawdown:.2f}%，处于正常的震荡调整期。"
        action_req = "分析该基金的当前状态，建议是继续定投熬过阵痛期，还是考虑部分转换。"
    else:
        situation = f"目前最大回撤仅为 {drawdown:.2f}%，整体走势非常稳健甚至可能处于盈利创新高状态。"
        action_req = "分析该基金为何表现如此优异，给出明确建议（继续重仓持有、逢高止盈部分、或者保持原状）。"

    prompt = f"""
你现在是一位专业、客观的量化基金研究员。
用户的持仓基金【{fund_name} ({fund_code})】{situation}

系统从全市场为你提取了当前表现最亮眼的同类开放式基金（供你参考）：
{top_funds_str}

请你给出一份简短、专业的诊断报告（字数控制在 500 字以内，使用 Markdown 格式）：
1. **诊断分析**：{action_req}（如果缺乏该基金的具体行业数据，请基于提供的数据逻辑推理，不要胡编乱造）。
2. **操作建议**：直接给出简单明了的操作建议。
3. **备选观察池**：如果需要换基或增加配置，请结合上面提供的全市场参考数据，推荐 1-2 只备选基金，并说明推荐理由。如果不建议换基，也可指出参考基金仅作对比观察。

请直接输出诊断报告正文。
"""

    logger.info(f"正在请求 DeepSeek 诊断 {fund_name} ...")
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是资深的基金量化研究员。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=1024
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"DeepSeek 诊断失败: {e}")
        return f"⚠️ AI 诊断失败，请检查网络或 API 余额：{e}"

def call_deepseek_portfolio_analysis(holdings_summary: list, total_mv: float, total_cost: float, total_pnl_pct: float) -> str:
    """
    调用 DeepSeek API 进行整体持仓结构诊断
    """
    if not settings.DEEPSEEK_API_KEY:
        logger.warning("DeepSeek API Key 未配置，无法进行 AI 诊断")
        return "⚠️ 系统未配置 DEEPSEEK_API_KEY，AI 诊断服务不可用。"

    client = OpenAI(
        api_key=settings.DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )

    holdings_str = "\n".join([
        f"- {h['fund_name']} ({h['fund_code']}): 成本 ¥{h['total_cost']:.2f}, 当前市值 ¥{h['market_value']:.2f}, "
        f"仓位占比 {h['weight']:.2f}%, 浮动盈亏 {h['unrealized_pnl_pct']:.2f}%"
        for h in holdings_summary
    ])

    prompt = f"""
你现在是一位资深的基金理财顾问和量化研究员。
用户请求你对其整体基金持仓结构进行诊断和优化建议。

【账户总览】
- 总投入成本：¥{total_cost:.2f}
- 当前总市值：¥{total_mv:.2f}
- 整体浮动盈亏率：{total_pnl_pct:.2f}%

【持仓明细（按市值占比排序）】
{holdings_str}

请给出一份专业、深入且直接的操作建议报告（字数控制在 800 字以内，使用 Markdown 格式）：
1. **仓位结构诊断**：分析当前持仓的集中度是否合理（例如某只基金占比是否过高），板块均衡性如何，整体风险暴露情况。
2. **个基点评与调仓建议**：结合各只基金的盈亏情况和仓位占比，明确指出哪些需要**增持**（逢低吸纳），哪些需要**减持/止盈**（仓位过重或盈利丰厚），哪些可以**保持观望**。
3. **下一步操作计划**：给出一个可执行的整体操作策略。

请直接输出诊断报告正文。
"""

    logger.info("正在请求 DeepSeek 整体持仓诊断 ...")
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是资深的基金理财顾问，说话客观直接，擅长资产配置和风险控制。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
            max_tokens=1500
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"DeepSeek 整体诊断失败: {e}")
        return f"⚠️ AI 诊断失败，请检查网络或 API 余额：{e}"

