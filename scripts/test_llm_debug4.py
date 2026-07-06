import asyncio, sys, os, json, re
sys.path.insert(0, 'E:\\market_report_systerm')
os.chdir('E:\\market_report_systerm')
from src.core.llm_client import call_llm

REPORT = """
中国智能手机行业风险分析：2025年Q1出货量6800万台同比下降8.2%，台积电3nm产能利用率95%导致芯片供应紧张。
华为份额从35%降至32%暗示竞争加剧。5G换机潮推动市场但消费降级压力导致增速放缓。
如果宏观经济持续承压市场规模可能进一步萎缩。中美贸易摩擦升级可能导致芯片禁运加剧。
AI手机成为2025年最显著技术趋势。头部企业可能通过并购或技术整合寻求突破。
"""

async def t():
    prompt = (
        f"Rate this report 1-10 on depth, insight, reliability, logic, contradiction, hypothesis.\n"
        f"Report:\n{REPORT}\n"
        f'Output ONLY: {{"depth":N,"insight":N,"reliability":N,"logic":N,"contradiction":N,"hypothesis":N,"total":N}}'
    )
    r = await call_llm(
        prompt=prompt,
        system_prompt='Output ONLY valid JSON. No other text.',
        max_tokens=200,
        temperature=0.0,
    )
    c = r.get('content', '')
    print(f'len={len(c)}, content={c[:300]}')
    m = re.search(r'\{[^{}]*\}', c)
    if m:
        print(f'parsed: {json.loads(m.group())}')

asyncio.run(t())
