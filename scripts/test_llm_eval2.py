import asyncio, sys, os, json, re
sys.path.insert(0, 'E:\\market_report_systerm')
os.chdir('E:\\market_report_systerm')
from src.core.llm_client import call_llm

async def t():
    r = await call_llm(
        prompt='Rate this text on depth(1-10) and insight(1-10). Output JSON only: {"depth":N,"insight":N}',
        system_prompt='Output ONLY valid JSON. No other text.',
        max_tokens=100,
        temperature=0.0,
    )
    c = r.get('content', '')
    print(f'raw: {repr(c)}')
    m = re.search(r'\{[^{}]*\}', c)
    if m:
        print(f'parsed: {json.loads(m.group())}')
    else:
        print('NO JSON MATCH')

asyncio.run(t())
