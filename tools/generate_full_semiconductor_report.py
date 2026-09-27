# -*- coding: utf-8 -*-
"""半导体行业报告完整生成流程"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.run_semiconductor_research import generate_research_data
from tools.revise_semiconductor_with_llm import revise_report
from tools.generate_semiconductor_report import content_to_html, parse_table_block
import json
from datetime import datetime

# 中文数字映射
cn_nums = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十']


def main():
    """执行完整的半导体行业报告生成流程"""
    print("=" * 60)
    print("半导体行业深度研究报告 - 完整生成流程")
    print("=" * 60)
    
    # 步骤1：生成研究数据
    print("\n步骤1：生成研究数据")
    print("-" * 40)
    research_data = generate_research_data()
    
    # 步骤2：LLM修订章节内容
    print("\n步骤2：LLM修订章节内容")
    print("-" * 40)
    revised_data = revise_report()
    
    # 步骤3：生成HTML和Word报告
    print("\n步骤3：生成HTML和Word报告")
    print("-" * 40)
    
    # 加载HTML模板
    template = (ROOT / 'templates' / 'professional_report.html').read_text(encoding='utf-8')
    
    # 生成目录
    toc_lines = []
    page_num = 3
    for i, section in enumerate(revised_data.get('sections', []), 1):
        title = section.get('title', '')
        num = cn_nums[i-1] if i <= len(cn_nums) else str(i)
        toc_lines.append(
            '<p class="toc-item-level1">{}、{}  ......  {}</p>'.format(num, title, page_num)
        )
        page_num += 3
    toc_html = '\n'.join(toc_lines)
    
    # 生成各章节HTML
    sections_html = []
    for i, section in enumerate(revised_data.get('sections', []), 1):
        title = section.get('title', '')
        content = section.get('content', '')
        num = cn_nums[i-1] if i <= len(cn_nums) else str(i)
        
        section_html = '<div class="section" id="section-{}">'.format(i)
        section_html += '<h1 class="chapter-title">{}、{}</h1>'.format(num, title)
        section_html += content_to_html(content)
        section_html += '</div>'
        sections_html.append(section_html)
    
    # 组装完整HTML
    full_html = template.replace('<!-- TOC_PLACEHOLDER -->', toc_html)
    full_html = full_html.replace('<!-- SECTIONS_PLACEHOLDER -->', '\n'.join(sections_html))
    
    # 保存HTML
    html_output = ROOT / 'output' / 'full_research' / 'semiconductor_report.html'
    html_output.parent.mkdir(parents=True, exist_ok=True)
    with open(html_output, 'w', encoding='utf-8') as f:
        f.write(full_html)
    print(f"HTML报告已生成: {html_output}")
    
    # 生成Word文档
    from src.converters.html_to_word import HTMLToWordConverter
    converter = HTMLToWordConverter()
    docx_output = ROOT / 'output' / 'full_research' / 'semiconductor_report.docx'
    converter.convert(str(html_output), str(docx_output))
    print(f"Word报告已生成: {docx_output}")
    
    print("\n" + "=" * 60)
    print("半导体行业深度研究报告生成完成！")
    print("=" * 60)
    print(f"报告位置: {docx_output}")
    print(f"HTML版本: {html_output}")
    print(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
