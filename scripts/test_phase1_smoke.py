import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['LLM_API_KEY'] = 'REDACTED_API_KEY'
os.environ['LLM_BASE_URL'] = 'https://api.deepseek.com/v1'
os.environ['LLM_PROVIDER'] = 'deepseek'
os.environ['LLM_MODEL'] = 'deepseek-v4-flash'
os.environ['LLM_CHEAP_MODEL'] = 'deepseek-v4-flash'


async def test_llm():
    from src.core.llm_client import call_llm
    result = await call_llm(
        prompt='Answer in one sentence: what is 1+1?',
        max_tokens=50,
        temperature=0.1,
    )
    success = result.get('success')
    content = str(result.get('content', ''))[:200]
    usage = result.get('usage', {})
    print(f'success={success}')
    print(f'content={content}')
    print(f'usage={usage}')
    return result


async def test_search():
    from src.skills.search_skill import SearchSkill
    skill = SearchSkill()
    result = await skill.execute(query='2026年中国新能源汽车市场', max_results=3)
    print(f'search_success={result.get("success", False)}')
    if result.get('results'):
        for r in result['results'][:3]:
            print(f'  - {r.get("title", "N/A")[:60]}')
    return result


async def test_skill_registry():
    from src.skills.registry import SkillRegistry
    registry = SkillRegistry()
    core_count = registry.register_core_skills()
    lc_count = registry.auto_discover_langchain_tools()
    all_skills = list(registry._skills.keys())
    print(f'core_skills={core_count}, langchain_tools={lc_count}')
    print(f'all_skills={all_skills[:20]}')
    return registry


async def test_storage():
    from pathlib import Path
    data_dir = Path('data')
    output_dir = Path('output')
    print(f'data_dir_exists={data_dir.exists()}')
    print(f'output_dir_exists={output_dir.exists()}')
    test_file = data_dir / 'test_write.tmp'
    test_file.write_text('test')
    content = test_file.read_text()
    test_file.unlink()
    print(f'storage_writable={content == "test"}')


async def main():
    print('=== 1.1 LLM Connection Test ===')
    try:
        r = await test_llm()
        print(f'LLM_TEST: {"PASS" if r.get("success") else "FAIL"}')
    except Exception as e:
        print(f'LLM_TEST: FAIL - {e}')

    print('\n=== 1.2 Search Engine Test ===')
    try:
        r = await test_search()
        print(f'SEARCH_TEST: {"PASS" if r.get("success") or r.get("results") else "FAIL"}')
    except Exception as e:
        print(f'SEARCH_TEST: FAIL - {e}')

    print('\n=== 1.3 SkillRegistry Test ===')
    try:
        await test_skill_registry()
        print('SKILL_REGISTRY_TEST: PASS')
    except Exception as e:
        print(f'SKILL_REGISTRY_TEST: FAIL - {e}')

    print('\n=== 1.4 Storage Test ===')
    try:
        await test_storage()
        print('STORAGE_TEST: PASS')
    except Exception as e:
        print(f'STORAGE_TEST: FAIL - {e}')


asyncio.run(main())
