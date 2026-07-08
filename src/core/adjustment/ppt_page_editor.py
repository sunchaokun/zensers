import os
from typing import Any, Dict, List, Optional

from src.core.adjustment.ppt_structure_editor import PptStructureEditor


class PptPageEditor:

    def __init__(self):
        self._structure_editor = PptStructureEditor()

    def edit(self, slide_index: int, slide_data: Dict, pptx,
             slide_data_list: List[Dict] = None,
             styles: Optional[Dict[str, Any]] = None,
             output_path: Optional[str] = None) -> Any:
        if not os.environ.get("PPT_ENABLE_L3_SINGLE_SLIDE"):
            return self._structure_editor.edit(
                slide_data_list or [], pptx, styles=styles, output_path=output_path
            )
        return self._replace_slide(pptx, slide_index, None)

    def _replace_slide(self, pptx, slide_index: int, new_slide) -> None:
        if not os.environ.get("PPT_ENABLE_L3_SINGLE_SLIDE"):
            raise NotImplementedError(
                "L3 single-slide replacement not enabled. "
                "Fallback: use L4 full re-render instead."
            )
        raise NotImplementedError("L3 XML swap not yet implemented")

    @staticmethod
    def _compute_section_index(slide_data_list: List[Dict], slide_index: int) -> int:
        count = 0
        for i in range(min(slide_index, len(slide_data_list))):
            if slide_data_list[i].get("slide_type") in ("section_title", "section-title"):
                count += 1
        return count
