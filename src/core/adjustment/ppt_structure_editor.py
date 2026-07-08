from typing import Dict, List, Optional, Any


class PptStructureEditor:

    def edit(self, slide_data_list: List[Dict], pptx=None,
             styles: Optional[Dict[str, Any]] = None,
             output_path: Optional[str] = None) -> Any:
        if pptx is not None and output_path is not None:
            from src.converters.html_to_ppt import HTMLToPPTConverter
            converter = HTMLToPPTConverter()
            final_styles = converter._merge_styles(None, styles)
            result = converter._create_pptx_document(slide_data_list, output_path, final_styles)
            return result
        return None

    def delete_slide(self, slide_data_list: List[Dict], slide_index: int) -> bool:
        if slide_index < 0 or slide_index >= len(slide_data_list):
            return False
        if slide_data_list[slide_index].get("slide_type") == "cover":
            return False
        if slide_data_list[slide_index].get("slide_type") == "end":
            return False
        slide_data_list.pop(slide_index)
        return True

    def add_slide(self, slide_data_list: List[Dict], slide_index: int,
                  new_slide_data: Dict) -> bool:
        if slide_index <= 0 or slide_index > len(slide_data_list) - 1:
            return False
        slide_data_list.insert(slide_index, new_slide_data)
        return True

    def reorder_slides(self, slide_data_list: List[Dict],
                       from_index: int, to_index: int) -> bool:
        if from_index < 1 or from_index >= len(slide_data_list) - 1:
            return False
        if to_index < 1 or to_index >= len(slide_data_list) - 1:
            return False
        if from_index == to_index:
            return True
        item = slide_data_list.pop(from_index)
        slide_data_list.insert(to_index, item)
        return True
