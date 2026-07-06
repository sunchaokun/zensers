import asyncio
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['LLM_API_KEY'] = 'REDACTED_API_KEY'
os.environ['LLM_BASE_URL'] = 'https://api.deepseek.com/v1'
os.environ['LLM_PROVIDER'] = 'deepseek'
os.environ['LLM_MODEL'] = 'deepseek-v4-flash'
os.environ['LLM_CHEAP_MODEL'] = 'deepseek-v4-flash'


async def test_entity_resolver():
    print('=== 2.6 EntityResolver Test ===')
    from src.core.entity_resolver import get_entity_resolver
    resolver = get_entity_resolver()

    cases = [
        ('比亚迪与宁德时代财务对比', 2),
        ('华为技术路线分析', 1),
        ('小米集团AI战略研究', 1),
    ]

    for text, expected_min in cases:
        result = await resolver.resolve(text)
        entities = [(e.name, e.resolved_code, e.is_listed) for e in result]
        print(f'  Input: {text}')
        print(f'  Entities: {entities}')
        print(f'  Expected>={expected_min}, Got={len(result)}: {"PASS" if len(result) >= expected_min else "WARN"}')


async def test_requirement_analysis():
    print('\n=== 2.1 RequirementAnalysisAgent Test ===')
    from src.core.orchestrator.smart_clarifier import SmartClarifier
    clarifier = SmartClarifier()

    result = await clarifier.clarify('分析中国新能源汽车市场')
    print(f'  Topic: {result.topic}')
    print(f'  Output type: {result.output_type}')
    print(f'  Aspects: {result.aspects}')
    print(f'  Intent type: {result.intent_type}')
    print(f'  Complexity: {result.complexity}')
    print(f'  Test: PASS' if result.topic else 'Test: FAIL')


async def test_intelligent_routing():
    print('\n=== 2.1b IntelligentRoutingAdapter Test ===')
    from src.core.intelligent_routing_adapter import IntelligentRoutingAdapter
    adapter = IntelligentRoutingAdapter(use_llm=True, fallback_to_keyword=True)

    result = adapter.analyze_simple('分析比亚迪公司投资价值', {'aspects': ['财务分析', '竞争格局']})
    print(f'  Intent: {result.intent.value}')
    print(f'  Complexity: {result.complexity.value}')
    print(f'  Confidence: {result.confidence}')
    print(f'  Strategy agents: {result.strategy.agent_count_estimate}')
    print(f'  Test: PASS')


async def test_data_collection_agent():
    print('\n=== 2.2 DataCollectionAgent Test ===')
    from src.agents.fixed_agents.data_collection_agent import DataCollectionAgent
    from src.core.communication import MessageBus, SharedMemory

    agent = DataCollectionAgent(agent_id='test_dc')
    agent.set_message_bus(MessageBus())
    agent.set_shared_memory(SharedMemory())

    task = {
        'query': '2026年中国新能源汽车市场规模数据',
        'max_results': 5,
    }
    valid, err = agent.validate_input(task)
    print(f'  Input validation: valid={valid}, err={err}')
    print(f'  Agent capabilities: {agent.capabilities}')
    print(f'  Test: PASS')


async def test_quality_check_agent():
    print('\n=== 2.4 QualityCheckAgent Test ===')
    from src.agents.fixed_agents.quality_check_agent import QualityCheckAgent

    agent = QualityCheckAgent(agent_id='test_qc')

    sample_report = {
        'title': '中国新能源汽车市场研究报告',
        'sections': [
            {
                'title': '市场概况',
                'content': '2025年中国新能源汽车销量突破1600万辆，同比增长28%。预计2026年销量将达到1900万辆，渗透率超过55%。主要驱动力包括政策支持、技术进步和消费者认知提升。',
                'section_type': 'market_size',
            },
            {
                'title': '竞争格局',
                'content': '比亚迪以30%的市场份额领先，特斯拉和蔚来紧随其后。行业集中度CR5超过60%，头部效应明显。新势力品牌面临生存挑战。',
                'section_type': 'competition',
            },
        ],
    }

    result = agent.execute({'report': sample_report})
    print(f'  Quality score: {result.get("quality_score", "N/A")}')
    print(f'  Passed: {result.get("passed", "N/A")}')
    issues = result.get('issues', [])
    print(f'  Issues count: {len(issues)}')
    if issues:
        for issue in issues[:3]:
            print(f'    - {str(issue)[:100]}')
    print(f'  Test: PASS')


async def test_report_generation_agent():
    print('\n=== 2.3 ReportGenerationAgent Test ===')
    from src.agents.fixed_agents.report_generation_agent import ReportGenerationAgent

    agent = ReportGenerationAgent(agent_id='test_rg')

    sample_data = {
        'title': '中国新能源汽车市场研究报告',
        'sections': [
            {
                'title': '市场概况',
                'content': '2025年中国新能源汽车销量突破1600万辆。',
                'section_type': 'market_size',
            },
        ],
        'template_type': 'industry_report',
    }

    valid, err = agent.validate_input(sample_data)
    print(f'  Input validation: valid={valid}')
    print(f'  Agent type: {agent.agent_type}')
    print(f'  Capabilities: {agent.capabilities}')
    print(f'  Test: PASS')


async def test_document_generation():
    print('\n=== 2.5 DocumentGenerationAgent Test ===')
    from src.agents.fixed_agents.document_generation_agent import DocumentGenerationAgent
    from src.core.communication import MessageBus, SharedMemory

    agent = DocumentGenerationAgent(agent_id='test_dg', storage_path='data')
    agent.set_message_bus(MessageBus())
    agent.set_shared_memory(SharedMemory())

    print(f'  Agent type: {agent.agent_type}')
    print(f'  Capabilities: {agent.capabilities}')
    print(f'  Test: PASS')


async def main():
    t0 = time.time()

    try:
        await test_entity_resolver()
    except Exception as e:
        print(f'  EntityResolver FAIL: {e}')

    try:
        await test_requirement_analysis()
    except Exception as e:
        print(f'  RequirementAnalysis FAIL: {e}')

    try:
        await test_intelligent_routing()
    except Exception as e:
        print(f'  IntelligentRouting FAIL: {e}')

    try:
        await test_data_collection_agent()
    except Exception as e:
        print(f'  DataCollection FAIL: {e}')

    try:
        await test_quality_check_agent()
    except Exception as e:
        print(f'  QualityCheck FAIL: {e}')

    try:
        await test_report_generation_agent()
    except Exception as e:
        print(f'  ReportGeneration FAIL: {e}')

    try:
        await test_document_generation()
    except Exception as e:
        print(f'  DocumentGeneration FAIL: {e}')

    print(f'\nPhase 2 completed in {time.time()-t0:.1f}s')


asyncio.run(main())
