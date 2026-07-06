import asyncio
import os
import sys
import time
import json
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['LLM_API_KEY'] = 'REDACTED_API_KEY'
os.environ['LLM_BASE_URL'] = 'https://api.deepseek.com/v1'
os.environ['LLM_PROVIDER'] = 'deepseek'
os.environ['LLM_MODEL'] = 'deepseek-v4-flash'
os.environ['LLM_CHEAP_MODEL'] = 'deepseek-v4-flash'


async def run_e2e_test(test_id, topic, output_type, custom_aspects=None):
    from src.core.orchestrator.orchestrator import ResearchOrchestrator
    from pathlib import Path

    print(f'\n{"="*60}')
    print(f'E2E: {test_id} | {topic} | {output_type}')
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
            output_format='html',
        )
        elapsed = time.time() - t0

        print(f'Status: {result.status}')
        print(f'Quality: {result.quality_score}')
        print(f'Agents: {result.agents_used}')
        print(f'Stages: {result.stages_completed}')
        print(f'Output: {result.output_path}')
        print(f'Doc: {result.document_path}')
        print(f'Time: {elapsed:.1f}s')
        print(f'Issues: {len(result.quality_issues) if result.quality_issues else 0}')

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
            'quality_issues_count': len(result.quality_issues) if result.quality_issues else 0,
        }

        result_file = Path(output_dir) / 'test_result.json'
        result_file.write_text(json.dumps(result_data, ensure_ascii=False, indent=2), encoding='utf-8')
        return result_data

    except Exception as e:
        elapsed = time.time() - t0
        print(f'ERROR after {elapsed:.1f}s: {e}')
        traceback.print_exc()
        return {
            'test_id': test_id,
            'status': 'error',
            'error': str(e),
            'elapsed_seconds': round(elapsed, 1),
        }


if __name__ == '__main__':
    test_id = sys.argv[1] if len(sys.argv) > 1 else 'E2E-1'
    topic = sys.argv[2] if len(sys.argv) > 2 else 'Chinese NEV market'
    output_type = sys.argv[3] if len(sys.argv) > 3 else 'market_brief'
    aspects_str = sys.argv[4] if len(sys.argv) > 4 else None
    aspects = aspects_str.split(',') if aspects_str else None

    result = asyncio.run(run_e2e_test(test_id, topic, output_type, aspects))
    print(f'\nDONE: {result.get("test_id")} status={result.get("status")} quality={result.get("quality_score", "N/A")} time={result.get("elapsed_seconds", 0)}s')
    sys.stdout.flush()
