import pytest
from src.core.adjustment.ppt_structure_editor import PptStructureEditor


def _make_slide_data_list():
    return [
        {"slide_type": "cover", "title": "Report"},
        {"slide_type": "content", "title": "Overview"},
        {"slide_type": "data", "title": "Revenue"},
        {"slide_type": "end", "title": "Thank You"},
    ]


class TestDeleteSlide:
    def test_delete_middle_slide(self):
        editor = PptStructureEditor()
        sdl = _make_slide_data_list()
        result = editor.delete_slide(sdl, 1)
        assert result is True
        assert len(sdl) == 3
        assert sdl[1]["title"] == "Revenue"

    def test_delete_cover_rejected(self):
        editor = PptStructureEditor()
        sdl = _make_slide_data_list()
        result = editor.delete_slide(sdl, 0)
        assert result is False
        assert len(sdl) == 4

    def test_delete_end_rejected(self):
        editor = PptStructureEditor()
        sdl = _make_slide_data_list()
        result = editor.delete_slide(sdl, 3)
        assert result is False
        assert len(sdl) == 4

    def test_delete_invalid_index(self):
        editor = PptStructureEditor()
        sdl = _make_slide_data_list()
        result = editor.delete_slide(sdl, 10)
        assert result is False


class TestAddSlide:
    def test_add_slide_at_end(self):
        editor = PptStructureEditor()
        sdl = _make_slide_data_list()
        new_sd = {"slide_type": "content", "title": "New Slide", "items": ["point1"]}
        result = editor.add_slide(sdl, 2, new_sd)
        assert result is True
        assert len(sdl) == 5
        assert sdl[2]["title"] == "New Slide"

    def test_add_slide_at_beginning_after_cover(self):
        editor = PptStructureEditor()
        sdl = _make_slide_data_list()
        new_sd = {"slide_type": "content", "title": "Inserted"}
        result = editor.add_slide(sdl, 1, new_sd)
        assert result is True
        assert sdl[1]["title"] == "Inserted"

    def test_add_at_cover_position_rejected(self):
        editor = PptStructureEditor()
        sdl = _make_slide_data_list()
        new_sd = {"slide_type": "content", "title": "Inserted"}
        result = editor.add_slide(sdl, 0, new_sd)
        assert result is False

    def test_add_at_invalid_index(self):
        editor = PptStructureEditor()
        sdl = _make_slide_data_list()
        new_sd = {"slide_type": "content", "title": "Inserted"}
        result = editor.add_slide(sdl, 10, new_sd)
        assert result is False


class TestReorderSlides:
    def test_reorder_swap_adjacent(self):
        editor = PptStructureEditor()
        sdl = _make_slide_data_list()
        result = editor.reorder_slides(sdl, 1, 2)
        assert result is True
        assert sdl[1]["title"] == "Revenue"
        assert sdl[2]["title"] == "Overview"

    def test_reorder_cover_rejected(self):
        editor = PptStructureEditor()
        sdl = _make_slide_data_list()
        result = editor.reorder_slides(sdl, 0, 2)
        assert result is False

    def test_reorder_end_rejected(self):
        editor = PptStructureEditor()
        sdl = _make_slide_data_list()
        result = editor.reorder_slides(sdl, 1, 3)
        assert result is False

    def test_reorder_invalid_indices(self):
        editor = PptStructureEditor()
        sdl = _make_slide_data_list()
        result = editor.reorder_slides(sdl, 1, 10)
        assert result is False
