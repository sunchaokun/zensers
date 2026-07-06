import asyncio, sys, os, json
sys.path.insert(0, 'E:\\market_report_systerm')
os.chdir('E:\\market_report_systerm')
from src.core.llm_client import call_llm

async def t():
    r = await call_llm(
        prompt='Say hello in JSON format: {"greeting": "hello"}',
        system_prompt='Output ONLY valid JSON.',
        max_tokens=100,
        temperature=0.0,
    )
    print(f'type={type(r)}')
    print(f'keys={list(r.keys()) if isinstance(r, dict) else "N/A"}')
    for k, v in (r.items() if isinstance(r, dict) else []):
        sv = str(v)[:100] if v else 'None'
        print(f'  {k}: {sv}')

asyncio.run(t())
