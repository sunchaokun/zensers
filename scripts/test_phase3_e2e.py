import asyncio
import os
import sys
import json
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['LLM_API_KEY'] = 'REDACTED_API_KEY'
os.environ['LLM_BASE_URL'] = 'https://api.deepseek.com/v1'
os.environ['LLM_PROVIDER'] = 'deepseek'
os.environ['LLM_MODEL'] = 'deepseek-v4-flash'
os.environ['LLM_CHEAP_MODEL'] = 'deepseek-v4-flash'


async def run_e2e_test(test_id, topic, output_type, custom_aspects=None):
    from src.core.orchestrator.orchestrator import ResearchOrchestrator

    print(f'\n{"="*60}')
    print(f'E2E Test: {test_id}')
    print(f'Topic: {topic}')
    print(f'Type: {output_type}')
    print(f'{"="*60}')

    output_dir = str(Path('output') / 'e2e_test' / test_id)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    orchestrator = ResearchOrchestrator()

    t0 = time.time()
    try:
        result = await orchestrator.research(
            user_input=topic,
            output_dir=output_dir,
            interaction_mode=False,
            output_type=output_type,
            custom_aspects=custom_aspects,
            output_format='docx',
        )
        elapsed = time.time() - t0

        print(f'\n--- Result ---')
        print(f'Status: {result.status}')
        print(f'Task ID: {result.task_id}')
        print(f'Topic: {result.topic}')
        print(f'Agents used: {result.agents_used}')
        print(f'Stages completed: {result.stages_completed}')
        print(f'Quality score: {result.quality_score}')
        print(f'Output path: {result.output_path}')
        print(f'Document path: {result.document_path}')
        print(f'Elapsed: {elapsed:.1f}s')
        print(f'Revision count: {result.revision_count}')

        if result.quality_issues:
            print(f'Quality issues ({len(result.quality_issues)}):')
            for issue in result.quality_issues[:5]:
                print(f'  - {str(issue)[:120]}')

        result_data = {
            'test_id': test_id,
            'topic': topic,
            'output_type': output_type,
            'status': result.status,
            'task_id': result.task_id,
            'agents_used': result.agents_used,
            'stages_completed': result.stages_completed,
            'quality_score': result.quality_score,
            'output_path': result.output_path,
            'document_path': result.document_path,
            'elapsed_seconds': round(elapsed, 1),
            'revision_count': result.revision_count,
            'quality_issues_count': len(result.quality_issues),
            'quality_issues': [str(i)[:200] for i in result.quality_issues[:10]],
        }

        result_file = Path(output_dir) / 'test_result.json'
        result_file.write_text(json.dumps(result_data, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'\nResult saved to: {result_file}')

        return result_data

    except Exception as e:
        elapsed = time.time() - t0
        print(f'\nERROR after {elapsed:.1f}s: {e}')
        import traceback
        traceback.print_exc()
        return {
            'test_id': test_id,
            'status': 'error',
            'error': str(e),
            'elapsed_seconds': round(elapsed, 1),
        }


async def main():
    results = []

    result1 = await run_e2e_test(
        'E2E-1',
        '中国新能源汽车市场深度研究',
        'industry_report',
        custom_aspects=['市场概况', '竞争格局', '技术趋势'],
    )
    results.append(result1)

    result2 = await run_e2e_test(
        'E2E-2',
        '比亚迪公司投资价值分析',
        'company_research',
        custom_aspects=['财务分析', '业务分析', '竞争地位'],
    )
    results.append(result2)

    result3 = await run_e2e_test(
        'E2E-3',
        'AI芯片竞品分析：英伟达vs AMD vs 华为昇腾',
        'competitor_analysis',
        custom_aspects=['产品对比', '技术路线', '市场策略'],
    )
    results.append(result3)

    summary_path = Path('output') / 'e2e_test' / 'summary.json'
    summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n\nAll E2E tests complete. Summary: {summary_path}')

    for r in results:
        status = r.get('status', 'unknown')
        elapsed = r.get('elapsed_seconds', 0)
        quality = r.get('quality_score', 'N/A')
        tid = r.get('test_id', '?')
        print(f'  {tid}: status={status}, quality={quality}, time={elapsed}s')


asyncio.run(main())
