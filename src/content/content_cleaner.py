# -*- coding: utf-8 -*-
"""
Content Cleaner
===============

Cleans upstream Agent output to ensure format compliance before
ContentOrchestrator processes it.

Handles:
1. Blacklist title detection (e.g., "章节内容", "Section Content")
2. JSON code block extraction (extract 'content' field from ```json blocks)
3. Internal debug field removal (self_check_*, data_points_used, etc.)
"""

import json
import logging
import re
from typing import Any, Dict

logger = logging.getLogger(__name__)

TITLE_BLACKLIST = frozenset({
    "章节内容", "Section Content", "内容", "正文",
    "Content", "Section", "章节", "正文内容",
})


def clean_section(section_data: Dict[str, Any]) -> Dict[str, Any]:
    """Clean a single section data dict.

    Mutates and returns the same dict.
    """
    title = section_data.get("title", "").strip()
    if title in TITLE_BLACKLIST:
        logger.debug(f"ContentCleaner: blacklisted title '{title}' -> ''")
        section_data["title"] = ""

    content = section_data.get("content", "")
    if content:
        cleaned = _extract_json_content(content)
        if cleaned is not content:
            logger.debug("ContentCleaner: extracted content from JSON code block")
            section_data["content"] = cleaned

    return section_data


def _extract_json_content(content: str) -> str:
    """If content is a ```json block with a 'content' field, extract it.

    Otherwise return content unchanged.
    """
    stripped = content.strip()
    if not stripped.startswith("```json"):
        return content

    lines = stripped.split("\n")
    code_end = len(lines)
    for i in range(len(lines) - 1, 0, -1):
        if lines[i].strip().startswith("```"):
            code_end = i
            break

    json_str = "\n".join(lines[1:code_end])
    try:
        data = json.loads(json_str)
        if isinstance(data, dict) and "content" in data:
            extracted = data["content"]
            if isinstance(extracted, str):
                return extracted
            return json.dumps(extracted, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        pass

    return content
