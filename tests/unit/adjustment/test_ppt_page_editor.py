import os
import pytest
from unittest.mock import MagicMock, patch
from src.core.adjustment.ppt_page_editor import PptPageEditor


def _make_slide_data_list():
    return [
        {"slide_type": "cover", "title": "Report"},
        {"slide_type": "section_title", "title": "Chapter 1"},
        {"slide_type": "content", "title": "Overview"},
        {"slide_type": "section-title", "title": "Chapter 2"},
        {"slide_type": "data", "title": "Revenue"},
    ]


class TestComputeSectionIndex:
    def test_no_section_titles_before_slide(self):
        result = PptPageEditor._compute_section_index(_make_slide_data_list(), 0)
        assert result == 0

    def test_one_section_before_slide(self):
        result = PptPageEditor._compute_section_index(_make_slide_data_list(), 2)
        assert result == 1

    def test_two_sections_before_slide(self):
        result = PptPageEditor._compute_section_index(_make_slide_data_list(), 4)
        assert result == 2

    def test_empty_list(self):
        result = PptPageEditor._compute_section_index([], 0)
        assert result == 0

    def test_index_beyond_list_length(self):
        result = PptPageEditor._compute_section_index(_make_slide_data_list(), 10)
        assert result == 2


class TestReplaceSlide:
    def test_without_feature_flag_raises(self):
        editor = PptPageEditor.__new__(PptPageEditor)
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(NotImplementedError, match="not enabled"):
                editor._replace_slide(MagicMock(), 0, MagicMock())

    def test_with_feature_flag_not_implemented(self):
        editor = PptPageEditor.__new__(PptPageEditor)
        with patch.dict(os.environ, {"PPT_ENABLE_L3_SINGLE_SLIDE": "1"}):
            with pytest.raises(NotImplementedError, match="not yet implemented"):
                editor._replace_slide(MagicMock(), 0, MagicMock())


class TestEdit:
    def test_edit_degrades_to_l4_when_no_flag(self):
        editor = PptPageEditor.__new__(PptPageEditor)
        mock_structure_editor = MagicMock()
        editor._structure_editor = mock_structure_editor
        sd_list = _make_slide_data_list()
        mock_pptx = MagicMock()
        mock_styles = MagicMock()

        with patch.dict(os.environ, {}, clear=True):
            editor.edit(2, sd_list[2], mock_pptx, sd_list, styles=mock_styles)
            mock_structure_editor.edit.assert_called_once_with(
                sd_list, mock_pptx, styles=mock_styles, output_path=None
            )
