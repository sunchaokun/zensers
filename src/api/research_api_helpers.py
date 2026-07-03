from typing import List, Dict, Any
from dataclasses import asdict
from datetime import datetime

from src.agents.fixed_agents.report_upgrade.models import ChapterWriteOutput
from src.agents.fixed_agents.report_upgrade.chapter_writer import ChapterWriter
from src.agents.fixed_agents.report_upgrade.data_registry import DataRegistry


def sections_to_chapters(sections: List[Dict]) -> List[ChapterWriteOutput]:
    key_conclusions_extractor = ChapterWriter._extract_conclusions
    chapters = []
    for sec in sections:
        key_conclusions = sec.get("key_conclusions", [])
        if not key_conclusions and sec.get("content"):
            key_conclusions = key_conclusions_extractor(sec.get("content", ""))
        chapters.append(ChapterWriteOutput(
            chapter_id=sec.get("id", ""),
            title=sec.get("title", sec.get("name", "")),
            content=sec.get("content", ""),
            data_points_used=[],
            key_conclusions=key_conclusions,
        ))
    return chapters


def restore_data_registry(session) -> DataRegistry:
    snapshot = session.get("_data_registry_snapshot")
    if snapshot:
        return DataRegistry.from_snapshot(snapshot)
    return DataRegistry()


def get_framework_config(session) -> Dict:
    cached = session.get("_framework_config")
    if cached:
        return cached
    try:
        from src.core.research_framework_manager import get_framework_config as _get_fc
        output_type = session.get("output_type") or session.get("research_context", {}).get("framework", {}).get("output_type", "industry_report")
        fc_obj = _get_fc(output_type)
        return {
            "name": fc_obj.name,
            "description": fc_obj.description,
            "section_weights": fc_obj.section_weights,
            "interaction_parameters": fc_obj.interaction_parameters,
        }
    except Exception:
        return {"name": "通用研究报告", "description": "通用研究"}


def get_task_structure(session) -> Dict:
    cached = session.get("_task_structure")
    if cached:
        return cached
    research_context = session.get("research_context", {})
    return {
        "topic": research_context.get("topic", ""),
        "directions": research_context.get("directions", []),
        "framework": research_context.get("framework"),
    }


def apply_revision_to_session(session, result, chapters, data_registry):
    report = session.setdefault("research_result", {}).setdefault("report", {})
    updated_sections = []
    for ch in chapters:
        updated_sections.append({
            "id": ch.chapter_id,
            "name": ch.title,
            "title": ch.title,
            "content": ch.content,
            "data_points": [asdict(dp) for dp in ch.data_points_used],
            "key_conclusions": ch.key_conclusions,
        })
    report["sections"] = updated_sections
    session["_data_registry_snapshot"] = data_registry.to_snapshot()
    revision_record = {
        "timestamp": datetime.now().isoformat(),
        "chapters_revised": len(result.get("chapter_results", [])),
        "global_review_score": result.get("global_review_score", 0),
        "global_review_passed": result.get("global_review_passed", False),
    }
    session.setdefault("_revision_history", []).append(revision_record)
