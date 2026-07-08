import pytest
from unittest.mock import MagicMock, AsyncMock
from src.core.adjustment.ppt_revision_service import (
    PptRevisionService, PptRevisionRequest, PptRevisionResult,
)
from src.core.adjustment.revision_types import RevisionOpType


def _make_request(**overrides):
    defaults = {
        "task_id": "t1",
        "source": "click",
        "slide_index": 1,
        "revision_type": "replace_text",
        "revision_level": "L1",
        "target_field": "title",
        "new_value": "New Title",
        "description": "",
    }
    defaults.update(overrides)
    return PptRevisionRequest(**defaults)


class TestPptRevisionRequest:
    def test_defaults(self):
        req = PptRevisionRequest(task_id="t1")
        assert req.source == "natural_language"
        assert req.slide_index is None
        assert req.revision_type == "modify"
        assert req.revision_level is None

    def test_click_request(self):
        req = _make_request()
        assert req.source == "click"
        assert req.target_field == "title"
        assert req.new_value == "New Title"


class TestPptRevisionResult:
    def test_success_result(self):
        result = PptRevisionResult(success=True, level="L1", message="done")
        assert result.success is True
        assert result.level == "L1"

    def test_failure_result(self):
        result = PptRevisionResult(success=False, level="L2", message="chart failed")
        assert result.success is False

    def test_l0_review_result(self):
        result = PptRevisionResult(
            success=True, level="L0", message="Review only"
        )
        assert result.level == "L0"


class TestValidateClickLevel:
    def test_modify_table_at_l1_corrected_to_l3(self):
        svc = PptRevisionService.__new__(PptRevisionService)
        req = _make_request(revision_type="modify_table", revision_level="L1")
        result = svc._validate_click_level("L1", req)
        assert result == "L3"

    def test_modify_chart_at_l1_corrected_to_l2(self):
        svc = PptRevisionService.__new__(PptRevisionService)
        req = _make_request(revision_type="modify_chart", revision_level="L1")
        result = svc._validate_click_level("L1", req)
        assert result == "L2"

    def test_add_at_l1_corrected_to_l4(self):
        svc = PptRevisionService.__new__(PptRevisionService)
        req = _make_request(revision_type="add", revision_level="L1")
        result = svc._validate_click_level("L1", req)
        assert result == "L4"

    def test_delete_at_l3_corrected_to_l4(self):
        svc = PptRevisionService.__new__(PptRevisionService)
        req = _make_request(revision_type="delete", revision_level="L3")
        result = svc._validate_click_level("L3", req)
        assert result == "L4"

    def test_valid_l1_replace_text_passes(self):
        svc = PptRevisionService.__new__(PptRevisionService)
        req = _make_request(revision_type="replace_text", revision_level="L1")
        result = svc._validate_click_level("L1", req)
        assert result == "L1"

    def test_unknown_type_passes(self):
        svc = PptRevisionService.__new__(PptRevisionService)
        req = _make_request(revision_type="custom_op", revision_level="L1")
        result = svc._validate_click_level("L1", req)
        assert result == "L1"


class TestDispatchL0:
    @pytest.mark.asyncio
    async def test_l0_returns_review_result(self):
        svc = PptRevisionService.__new__(PptRevisionService)
        req = _make_request(revision_level="L0")
        result = await svc._dispatch("L0", req)
        assert result.success is True
        assert result.level == "L0"
        assert "no modification" in result.message.lower() or "review" in result.message.lower()
