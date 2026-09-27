# -*- coding: utf-8 -*-
"""生成半导体行业深度研究报告 - HTML和Word版本"""

import json
import re
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.converters.html_to_word import HTMLToWordConverter

# 加载研究数据
research_data_path = ROOT / 'output' / 'full_research' / 'semiconductor_research_result.json'
if not research_data_path.exists():
    print(f"错误：未找到研究数据文件 {research_data_path}")
    print("请先运行研究流程生成数据")
    sys.exit(1)

with open(research_data_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

# 加载HTML模板
template = (ROOT / 'templates' / 'professional_report.html').read_text(encoding='utf-8')

# 中文数字映射
cn_nums = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十']

# 生成目录
toc_lines = []
page_num = 3
for i, section in enumerate(data.get('sections', []), 1):
    title = section.get('title', '')
    num = cn_nums[i-1] if i <= len(cn_nums) else str(i)
    toc_lines.append(
        '<p class="toc-item-level1">{}、{}  ......  {}</p>'.format(num, title, page_num)
    )
    page_num += 3
toc_html = '\n'.join(toc_lines)


def strip_markdown(text):
    """清理markdown格式"""
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'`([^`]*)`', r'\1', text)
    return text.strip()


def clean_heading_numbering(text):
    """清理标题中的冗余编号"""
    text = strip_markdown(text)
    text = re.sub(r'^[①②③④⑤⑥⑦⑧⑨⑩]\s*', '', text)
    text = re.sub(r'^\d+[.、]\s*', '', text)
    text = re.sub(r'^[一二三四五六七八九十]+[、.]\s*', '', text)
    text = re.sub(r'^第[一二三四五六七八九十]+部分[：:]\s*', '', text)
    return text.strip()


def parse_table_block(lines, start_idx):
    """解析连续表格行"""
    headers = []
    rows = []
    idx = start_idx
    while idx < len(lines):
        line = lines[idx].strip()
        if not line.startswith('|'):
            break
        cells = [c.strip() for c in line.split('|')]
        if line.endswith('|'):
            cells = cells[1:-1]
        else:
            cells = cells[1:]
        if not headers:
            headers = [c for c in cells if c and c != '---']
        else:
            if not all(c in ['---', ''] for c in cells):
                rows.append(cells)
        idx += 1
    return headers, rows, idx


def content_to_html(content):
    """将markdown内容转为HTML，自动修正标题层级"""
    lines = content.split('\n')
    heading_lines = []

    for idx, line in enumerate(lines):
        m = re.match(r'^(#{1,6})\s+(.+)$', line.strip())
        if m:
            level = len(m.group(1))
            text = clean_heading_numbering(m.group(2))
            heading_lines.append((idx, level, text))

    has_h2 = any(level == 2 for _, level, _ in heading_lines)

    if not has_h2 and heading_lines:
        new_lines = list(lines)
        for idx, level, text in heading_lines:
            if level == 3:
                new_lines[idx] = '## {}'.format(text)
            elif level == 4:
                new_lines[idx] = '### {}'.format(text)
            elif level < 3:
                new_lines[idx] = '## {}'.format(text)
        lines = new_lines

    parts = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or '统计口径' in line:
            i += 1
            continue

        if line.startswith('|'):
            headers, rows, end_idx = parse_table_block(lines, i)
            if headers:
                parts.append('<table><thead><tr>')
                for h in headers:
                    parts.append('<th>{}</th>'.format(h))
                parts.append('</tr></thead><tbody>')
                for row in rows:
                    parts.append('<tr>')
                    for cell in row:
                        parts.append('<td>{}</td>'.format(cell))
                    parts.append('</tr>')
                parts.append('</tbody></table>')
            i = end_idx
            continue

        m = re.match(r'^(#{2,4})\s+(.+)$', line)
        if m:
            level = len(m.group(1))
            t = clean_heading_numbering(m.group(2))
            if level == 2:
                parts.append('<h2 class="section-title">{}</h2>'.format(t))
            elif level == 3:
                parts.append('<h3 class="subsection-title">{}</h3>'.format(t))
            elif level == 4:
                parts.append('<h4 class="sub-subsection-title">{}</h4>'.format(t))
            i += 1
            continue

        if line.startswith('- ') or line.startswith('* '):
            text = strip_markdown(line[2:])
            if text:
                parts.append('<p>{}</p>'.format(text))
            i += 1
            continue

        m2 = re.match(r'^(\d+)[.、]\s*(.+)$', line)
        if m2:
            text = strip_markdown(m2.group(2))
            if text:
                parts.append('<p>{}</p>'.format(text))
            i += 1
            continue

        text = strip_markdown(line)
        text = re.sub(r'<[^>]+>', '', text).strip()
        if text:
            parts.append('<p>{}</p>'.format(text))
        i += 1

    return '\n'.join(parts)


# 生成各章节HTML
sections_html = []
for i, section in enumerate(data.get('sections', []), 1):
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
converter = HTMLToWordConverter()
docx_output = ROOT / 'output' / 'full_research' / 'semiconductor_report.docx'
converter.convert(str(html_output), str(docx_output))
print(f"Word报告已生成: {docx_output}")
