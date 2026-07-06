import asyncio, sys, os, json, re
sys.path.insert(0, 'E:\\market_report_systerm')
os.chdir('E:\\market_report_systerm')
from src.core.llm_client import call_llm

REPORT = "中国智能手机行业风险分析：出货量6800万台同比下降8.2%，芯片供应紧张。"

async def t():
    prompt = (
        f"Rate this report 1-10 on depth, insight, reliability.\n"
        f"Report: {REPORT}\n"
        f'Output JSON: {{"depth":N,"insight":N,"reliability":N}}'
    )
    r = await call_llm(
        prompt=prompt,
        system_prompt="You are a report quality evaluator.",
        max_tokens=200,
        temperature=0.0,
    )
    c = r.get('content', '')
    print(f'len={len(c)}, content={c[:300]}')

asyncio.run(t())
