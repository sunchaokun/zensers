import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from src.core.adjustment.revision_types import (
    AnalysisResult, RevisionOpType,
)

logger = logging.getLogger(__name__)


@dataclass
class PptRevisionRequest:
    task_id: str
    source: str = "natural_language"
    slide_index: Optional[int] = None
    slide_title: Optional[str] = None
    content_keyword: Optional[str] = None
    shape_name: Optional[str] = None
    shape_index: Optional[int] = None
    revision_type: str = "modify"
    description: str = ""
    new_chart_type: Optional[str] = None
    new_data: Optional[Dict] = None
    target_field: Optional[str] = None
    new_value: Optional[str] = None
    intent_analysis: Optional[AnalysisResult] = None
    revision_level: Optional[str] = None


@dataclass
class PptRevisionResult:
    success: bool
    level: str
    message: str = ""
    intent_analysis: Optional[AnalysisResult] = None
    error: Optional[str] = None


class PptRevisionService:

    INCONSISTENT_MAP = {
        RevisionOpType.MODIFY_TABLE: {"L1"},
        RevisionOpType.MODIFY_CHART: {"L1"},
        RevisionOpType.ADD: {"L1", "L2", "L3"},
        RevisionOpType.DELETE: {"L1", "L2", "L3"},
    }

    def __init__(self, slide_data_store, chart_generator=None,
                 image_provider=None):
        self.store = slide_data_store
        self.pptx_path = slide_data_store.pptx_path
        from src.core.adjustment.ppt_revision_router import PptRevisionRouter
        from src.core.adjustment.ppt_slide_locator import PptSlideLocator
        from src.core.adjustment.ppt_atomic_editor import PptAtomicEditor
        from src.core.adjustment.ppt_element_editor import PptElementEditor
        from src.core.adjustment.ppt_page_editor import PptPageEditor
        from src.core.adjustment.ppt_structure_editor import PptStructureEditor
        from src.core.adjustment.ppt_version_manager import PptVersionManager
        self.router = PptRevisionRouter()
        self.locator = PptSlideLocator()
        self.atomic = PptAtomicEditor()
        self.element = PptElementEditor()
        self.page = PptPageEditor()
        self.structure = PptStructureEditor()
        self.version_mgr = PptVersionManager(
            revisions_dir=os.path.join(
                os.path.dirname(slide_data_store._data_dir), "revisions"
            )
        )

    async def revise(self, request: PptRevisionRequest) -> PptRevisionResult:
        self.pptx_path = self.store.pptx_path
        if self.pptx_path and os.path.exists(self.pptx_path):
            self.version_mgr.create_snapshot(
                request.task_id, self.pptx_path,
                request.revision_level or "L0",
                request.description,
            )
        if request.source == "click":
            level = request.revision_level or "L1"
            level = self._validate_click_level(level, request)
        else:
            try:
                routed = await self.router.route(
                    request.description,
                    self.store.load(request.task_id),
                    {"task_id": request.task_id},
                )
                request.revision_level = routed.revision_level
                request.intent_analysis = routed.intent_analysis
                request.slide_index = routed.slide_index
                level = routed.revision_level
            except Exception as e:
                logger.error(f"Routing failed: {e}")
                level = request.revision_level or "L3"
        result = await self._dispatch(level, request)
        if result.success:
            try:
                slide_data_list = self.store.load(request.task_id)
                self.store.persist(request.task_id, slide_data_list)
            except Exception:
                pass
        return result

    def _validate_click_level(self, level: str, request: PptRevisionRequest) -> str:
        try:
            op_type = RevisionOpType(request.revision_type)
        except ValueError:
            return level
        blocked = self.INCONSISTENT_MAP.get(op_type, set())
        if level in blocked:
            from src.core.adjustment.ppt_revision_router import PptRevisionRouter
            correct_level = PptRevisionRouter.DEFAULT_LEVEL_MAP.get(op_type, "L4")
            logger.warning(
                f"Click level {level} inconsistent with revision_type "
                f"{request.revision_type}, correcting to {correct_level}"
            )
            return correct_level
        return level

    async def _dispatch(self, level: str, request: PptRevisionRequest) -> PptRevisionResult:
        if level == "L0":
            return PptRevisionResult(
                success=True, level="L0",
                message="Review only — no modification applied",
                intent_analysis=request.intent_analysis,
            )
        elif level == "L1":
            return self.atomic.edit(request, self.store, self.pptx_path)
        elif level == "L2":
            return self.element.edit(request, self.store, self.pptx_path)
        elif level == "L3":
            return self._dispatch_l3(request)
        elif level == "L4":
            return self._dispatch_l4(request)
        elif level.startswith("L5"):
            return await self._rollback_framework(request)
        return PptRevisionResult(
            success=False, level=level, error=f"Unknown level: {level}"
        )

    def _dispatch_l3(self, request: PptRevisionRequest) -> PptRevisionResult:
        slide_data_list = self.store.load(request.task_id)
        slide_index = request.slide_index or 0
        if slide_index >= len(slide_data_list):
            return PptRevisionResult(
                success=False, level="L3", error="Slide index out of range"
            )
        result = self.page.edit(
            slide_index, slide_data_list[slide_index],
            pptx=None, slide_data_list=slide_data_list,
            output_path=self.pptx_path,
        )
        self.store.persist(request.task_id, slide_data_list)
        return PptRevisionResult(
            success=True, level="L3",
            message="Page re-rendered (L3 degraded to L4)"
        )

    def _dispatch_l4(self, request: PptRevisionRequest) -> PptRevisionResult:
        slide_data_list = self.store.load(request.task_id)
        self.structure.edit(
            slide_data_list, output_path=self.pptx_path,
        )
        self.store.persist(request.task_id, slide_data_list)
        return PptRevisionResult(
            success=True, level="L4", message="Full re-render completed"
        )

    async def _rollback_framework(self, request: PptRevisionRequest) -> PptRevisionResult:
        return PptRevisionResult(
            success=False, level="L5",
            message="Framework rollback requires state machine integration",
            error="L5 rollback not yet integrated with ConversationStateMachine",
        )
