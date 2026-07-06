"""
Minimal E2E test - just the orchestrator core flow with market_brief (fastest)
"""
import asyncio
import os
import sys
import json
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['LLM_API_KEY'] = 'REDACTED_API_KEY'
os.environ['LLM_BASE_URL'] = 'https://api.deepseek.com/v1'
os.environ['LLM_PROVIDER'] = 'deepseek'
os.environ['LLM_MODEL'] = 'deepseek-v4-flash'
os.environ['LLM_CHEAP_MODEL'] = 'deepseek-v4-flash'


async def run_minimal_e2e():
    from src.core.orchestrator.orchestrator import ResearchOrchestrator
    from pathlib import Path

    output_dir = str(Path('output') / 'e2e_test' / 'E2E-MINIMAL')
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    print("Starting minimal E2E test (market_brief)...")
    t0 = time.time()

    try:
        orchestrator = ResearchOrchestrator()
        result = await orchestrator.research(
            user_input="China AI market overview 2026",
            output_dir=output_dir,
            interaction_mode=False,
            output_type='market_brief',
            custom_aspects=['market size', 'key trends'],
            output_format='html',
        )
        elapsed = time.time() - t0

        print(f"\n{'='*60}")
        print(f"RESULT:")
        print(f"  Status: {result.status}")
        print(f"  Quality: {result.quality_score}")
        print(f"  Agents: {result.agents_used}")
        print(f"  Stages: {result.stages_completed}")
        print(f"  Output: {result.output_path}")
        print(f"  Doc: {result.document_path}")
        print(f"  Time: {elapsed:.1f}s")
        print(f"  Issues: {len(result.quality_issues) if result.quality_issues else 0}")
        if result.quality_issues:
            for issue in result.quality_issues[:3]:
                print(f"    - {str(issue)[:150]}")
        print(f"{'='*60}")

        result_data = {
            'test_id': 'E2E-MINIMAL',
            'status': result.status,
            'quality_score': result.quality_score,
            'elapsed_seconds': round(elapsed, 1),
            'output_path': result.output_path,
            'document_path': result.document_path,
        }
        Path(output_dir).joinpath('result.json').write_text(
            json.dumps(result_data, ensure_ascii=False, indent=2), encoding='utf-8')
        return result

    except Exception as e:
        elapsed = time.time() - t0
        print(f"\nERROR after {elapsed:.1f}s: {e}")
        traceback.print_exc()
        return None


asyncio.run(run_minimal_e2e())
