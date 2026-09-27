# -*- coding: utf-8 -*-
"""半导体行业报告LLM修订脚本"""

import json
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 加载环境变量
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')

# 加载研究数据
research_data_path = ROOT / 'output' / 'full_research' / 'semiconductor_research_result.json'
if not research_data_path.exists():
    print(f"错误：未找到研究数据文件 {research_data_path}")
    print("请先运行 run_semiconductor_research.py 生成数据")
    sys.exit(1)

with open(research_data_path, 'r', encoding='utf-8') as f:
    research_data = json.load(f)

# 修订提示词
revision_prompts = {
    "industry_overview": """
请修订以下关于半导体行业概览的内容，使其更加专业、深入、符合德勤咨询公司风格：

原始内容：
{content}

修订要求：
1. 增强专业性和深度，使用更多行业术语
2. 补充更多权威数据（SIA、WSTS、中国半导体行业协会等）
3. 增强段落之间的逻辑连贯性
4. 避免列表和要点，使用段落式写作
5. 每个主要观点需要详细阐述，不少于200字
6. 总字数不少于3000字
7. 保持客观中立的立场
8. 使用专业咨询公司风格（德勤/麦肯锡/BCG）
""",
    "market_size": """
请修订以下关于半导体市场规模的内容，使其更加专业、深入、符合德勤咨询公司风格：

原始内容：
{content}

修订要求：
1. 增强专业性和深度，使用更多行业术语
2. 补充更多权威数据（SIA、WSTS、中国半导体行业协会等）
3. 增强段落之间的逻辑连贯性
4. 避免列表和要点，使用段落式写作
5. 每个主要观点需要详细阐述，不少于200字
6. 总字数不少于3000字
7. 保持客观中立的立场
8. 使用专业咨询公司风格（德勤/麦肯锡/BCG）
""",
    "industry_chain": """
请修订以下关于半导体产业链的内容，使其更加专业、深入、符合德勤咨询公司风格：

原始内容：
{content}

修订要求：
1. 增强专业性和深度，使用更多行业术语
2. 补充更多权威数据
3. 增强段落之间的逻辑连贯性
4. 避免列表和要点，使用段落式写作
5. 每个主要观点需要详细阐述，不少于200字
6. 总字数不少于3000字
7. 保持客观中立的立场
8. 使用专业咨询公司风格（德勤/麦肯锡/BCG）
""",
    "competitive_landscape": """
请修订以下关于半导体竞争格局的内容，使其更加专业、深入、符合德勤咨询公司风格：

原始内容：
{content}

修订要求：
1. 增强专业性和深度，使用更多行业术语
2. 补充更多权威数据
3. 增强段落之间的逻辑连贯性
4. 避免列表和要点，使用段落式写作
5. 每个主要观点需要详细阐述，不少于200字
6. 总字数不少于3000字
7. 保持客观中立的立场
8. 使用专业咨询公司风格（德勤/麦肯锡/BCG）
""",
    "technology_trends": """
请修订以下关于半导体技术趋势的内容，使其更加专业、深入、符合德勤咨询公司风格：

原始内容：
{content}

修订要求：
1. 增强专业性和深度，使用更多行业术语
2. 补充更多权威数据
3. 增强段落之间的逻辑连贯性
4. 避免列表和要点，使用段落式写作
5. 每个主要观点需要详细阐述，不少于200字
6. 总字数不少于3000字
7. 保持客观中立的立场
8. 使用专业咨询公司风格（德勤/麦肯锡/BCG）
""",
    "policy_environment": """
请修订以下关于半导体政策环境的内容，使其更加专业、深入、符合德勤咨询公司风格：

原始内容：
{content}

修订要求：
1. 增强专业性和深度，使用更多行业术语
2. 补充更多权威数据
3. 增强段落之间的逻辑连贯性
4. 避免列表和要点，使用段落式写作
5. 每个主要观点需要详细阐述，不少于200字
6. 总字数不少于3000字
7. 保持客观中立的立场
8. 使用专业咨询公司风格（德勤/麦肯锡/BCG）
""",
    "risk_analysis": """
请修订以下关于半导体风险分析的内容，使其更加专业、深入、符合德勤咨询公司风格：

原始内容：
{content}

修订要求：
1. 增强专业性和深度，使用更多行业术语
2. 补充更多权威数据
3. 增强段落之间的逻辑连贯性
4. 避免列表和要点，使用段落式写作
5. 每个主要观点需要详细阐述，不少于200字
6. 总字数不少于3000字
7. 保持客观中立的立场
8. 使用专业咨询公司风格（德勤/麦肯锡/BCG）
""",
    "investment_recommendations": """
请修订以下关于半导体投资建议的内容，使其更加专业、深入、符合德勤咨询公司风格：

原始内容：
{content}

修订要求：
1. 增强专业性和深度，使用更多行业术语
2. 补充更多权威数据
3. 增强段落之间的逻辑连贯性
4. 避免列表和要点，使用段落式写作
5. 每个主要观点需要详细阐述，不少于200字
6. 总字数不少于3000字
7. 保持客观中立的立场
8. 使用专业咨询公司风格（德勤/麦肯锡/BCG）
"""
}


def revise_chapter_content(chapter_id, content):
    """使用LLM修订章节内容"""
    if chapter_id not in revision_prompts:
        print(f"警告：未找到章节 {chapter_id} 的修订提示词")
        return content
    
    prompt = revision_prompts[chapter_id].format(content=content)
    
    # 这里应该调用LLM API进行修订
    # 由于是示例，我们返回原始内容
    print(f"  警告：LLM修订功能未实现，使用原始内容")
    return content


def revise_report():
    """修订整个报告"""
    print("开始修订半导体行业报告...")
    
    revised_data = {
        "title": research_data["title"],
        "subtitle": research_data["subtitle"],
        "institution": research_data["institution"],
        "date": research_data["date"],
        "sections": []
    }
    
    for section in research_data["sections"]:
        print(f"修订章节: {section['title']}")
        
        revised_content = revise_chapter_content(section["id"], section["content"])
        
        revised_data["sections"].append({
            "id": section["id"],
            "title": section["title"],
            "content": revised_content
        })
    
    # 保存修订结果
    output_dir = ROOT / 'output' / 'full_research'
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = output_dir / 'semiconductor_revised_report_llm.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(revised_data, f, ensure_ascii=False, indent=2)
    
    print(f"修订报告已保存: {output_file}")
    return revised_data


if __name__ == "__main__":
    revise_report()
