import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path


def _make_session(sections=None, output_type=None, framework_config=None, data_registry_snapshot=None, task_structure=None):
    session = {
        "research_result": {
            "status": "completed",
            "report": {
                "sections": sections or [],
                "topic": "新能源汽车",
            },
        },
        "research_context": {
            "topic": "新能源汽车",
            "directions": ["市场分析", "竞争格局"],
            "framework": framework_config or {},
        },
        "quality_state": {
            "phase": "reviewing",
            "section_scores": {},
        },
    }
    if output_type:
        session["output_type"] = output_type
    if data_registry_snapshot:
        session["_data_registry_snapshot"] = data_registry_snapshot
    if task_structure:
        session["_task_structure"] = task_structure
    return session


class TestSectionsToChapters:
    def test_converts_basic_sections(self):
        from src.api.research_api_helpers import sections_to_chapters
        sections = [
            {"id": "ch1", "title": "市场规模", "content": "市场规模达2000亿元"},
            {"id": "ch2", "title": "竞争格局", "content": "CR3达65%"},
        ]
        result = sections_to_chapters(sections)
        assert len(result) == 2
        assert result[0].chapter_id == "ch1"
        assert result[0].title == "市场规模"
        assert "2000" in result[0].content

    def test_title_key_preferred_over_name(self):
        from src.api.research_api_helpers import sections_to_chapters
        sections = [{"id": "ch1", "title": "正确标题", "name": "错误名称", "content": "内容"}]
        result = sections_to_chapters(sections)
        assert result[0].title == "正确标题"

    def test_name_key_as_fallback(self):
        from src.api.research_api_helpers import sections_to_chapters
        sections = [{"id": "ch1", "name": "只有名称", "content": "内容"}]
        result = sections_to_chapters(sections)
        assert result[0].title == "只有名称"

    def test_empty_sections(self):
        from src.api.research_api_helpers import sections_to_chapters
        result = sections_to_chapters([])
        assert result == []


class TestRestoreDataRegistry:
    def test_restores_from_snapshot(self):
        from src.api.research_api_helpers import restore_data_registry
        from src.agents.fixed_agents.report_upgrade.data_registry import DataRegistry
        dr = DataRegistry()
        dr.register(metric="营收", value="2000", unit="亿元", chapter_id="ch1", source="test")
        snapshot = dr.to_snapshot()
        session = _make_session(data_registry_snapshot=snapshot)
        registry = restore_data_registry(session)
        assert registry is not None
        assert "营收" in registry.to_snapshot().get("metrics", {})

    def test_creates_empty_when_no_snapshot(self):
        from src.api.research_api_helpers import restore_data_registry
        session = _make_session()
        registry = restore_data_registry(session)
        assert registry is not None


class TestGetFrameworkConfig:
    def test_returns_cached_config(self):
        from src.api.research_api_helpers import get_framework_config
        session = _make_session()
        session["_framework_config"] = {"name": "缓存框架", "description": "缓存"}
        result = get_framework_config(session)
        assert result["name"] == "缓存框架"

    def test_returns_default_on_failure(self):
        from src.api.research_api_helpers import get_framework_config
        session = _make_session()
        result = get_framework_config(session)
        assert "name" in result


class TestGetTaskStructure:
    def test_returns_cached_task_structure(self):
        from src.api.research_api_helpers import get_task_structure
        session = _make_session(task_structure={"topic": "缓存主题", "sections": []})
        result = get_task_structure(session)
        assert result["topic"] == "缓存主题"

    def test_extracts_from_research_context(self):
        from src.api.research_api_helpers import get_task_structure
        session = _make_session()
        result = get_task_structure(session)
        assert result["topic"] == "新能源汽车"
        assert len(result["directions"]) == 2


class TestApplyRevisionToSession:
    def test_writes_chapters_back_to_session(self):
        from src.api.research_api_helpers import apply_revision_to_session
        from src.agents.fixed_agents.report_upgrade.models import ChapterWriteOutput, DataPoint
        from src.agents.fixed_agents.report_upgrade.data_registry import DataRegistry
        from datetime import datetime

        session = _make_session()
        chapters = [
            ChapterWriteOutput(
                chapter_id="ch1", title="市场规模",
                content="修订后内容", data_points_used=[], key_conclusions=["结论1"],
            )
        ]
        registry = DataRegistry()
        result = {"chapter_results": [], "global_review_score": 85, "global_review_passed": True}

        apply_revision_to_session(session, result, chapters, registry)

        assert session["research_result"]["report"]["sections"][0]["content"] == "修订后内容"
        assert session["research_result"]["report"]["sections"][0]["key_conclusions"] == ["结论1"]
        assert "_data_registry_snapshot" in session
        assert "_revision_history" in session
