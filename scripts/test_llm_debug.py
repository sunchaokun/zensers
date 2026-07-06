import asyncio, sys, os
sys.path.insert(0, 'E:\\market_report_systerm')
os.chdir('E:\\market_report_systerm')
from src.core.llm_client import call_llm

async def t():
    r = await call_llm(
        prompt='Output this JSON only: {"a": 1, "b": 2}',
        system_prompt='Output ONLY valid JSON, nothing else.',
        max_tokens=100,
        temperature=0.0,
    )
    c = r.get('content', 'NONE')
    print(f'type={type(c)}, len={len(c)}, content={c[:200]}')

asyncio.run(t())
