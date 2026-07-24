# PPT Data-Driven Generation Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the data-driven PPT generation pipeline — user provides files (Word/PDF/Excel/text), system extracts structured data, confirms intent, supplements gaps, generates PPT.

**Architecture:** Extract full data into backend session, feedback summary to user via chat, route by intent (PPT vs other), clarify requirements via dialogue, supplement data gaps, then hand off to existing SlideDataBuilder → SlideOutlineBuilder → HTMLToPPTConverter pipeline.

**Tech Stack:** Python 3.13, pytest, python-docx, pdfplumber, openpyxl, dataclasses

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `src/core/adjustment/extraction_types.py` | ExtractionResult, ExtractionSummary, SectionSummary, DataParser ABC |
| Create | `src/core/adjustment/ppt_input_adapter.py` | PptInputAdapter, DocxDataParser, PdfDataParser, ExcelDataParser, TextDataParser, CsvDataParser, JsonDataParser |
| Create | `src/core/adjustment/ppt_requirement_extractor.py` | PptRequirement dataclass, PptRequirementExtractor |
| Create | `src/core/adjustment/ppt_data_supplementer.py` | DataGap dataclass, PptDataSupplementer |
| Create | `tests/unit/adjustment/test_extraction_types.py` | Tests for extraction dataclasses |
| Create | `tests/unit/adjustment/test_ppt_input_adapter.py` | Tests for PptInputAdapter and all parsers |
| Create | `tests/unit/adjustment/test_ppt_requirement_extractor.py` | Tests for PptRequirementExtractor |
| Create | `tests/unit/adjustment/test_ppt_data_supplementer.py` | Tests for PptDataSupplementer |
| Modify | `src/core/intent_types.py:33-42` | Add PPT_GENERATION to IntentType enum |
| Modify | `src/core/dialogue/state_machine.py:20-29` | Add DATA_EXTRACTED, REQUIREMENT_CONFIRM, DATA_SUPPLEMENT to ConversationState |
| Modify | `src/core/dialogue/state_machine.py:45-92` | Add transitions for new states |
| Modify | `src/core/dialogue/state_machine.py:278-296` | Add suggest_next cases for new states |
| Create | `tests/unit/dialogue/test_state_machine_ppt_states.py` | Tests for new states and transitions |

---

## Task 1: ExtractionResult + ExtractionSummary + SectionSummary Dataclasses

**Files:**
- Create: `src/core/adjustment/extraction_types.py`
- Test: `tests/unit/adjustment/test_extraction_types.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/adjustment/test_extraction_types.py
import pytest
from src.core.adjustment.extraction_types import (
    ExtractionResult, ExtractionSummary, SectionSummary, DataParser,
)


class TestSectionSummary:
    def test_create_with_defaults(self):
        s = SectionSummary(title="Intro", page_range="1-3")
        assert s.title == "Intro"
        assert s.page_range == "1-3"
        assert s.content_preview == ""
        assert s.has_table is False
        assert s.has_chart is False

    def test_create_with_all_fields(self):
        s = SectionSummary(
            title="Market", page_range="4-10",
            content_preview="The market is growing...",
            has_table=True, has_chart=True,
        )
        assert s.has_table is True
        assert s.has_chart is True


class TestExtractionSummary:
    def test_create_with_defaults(self):
        es = ExtractionSummary(
            file_count=1, total_pages=10,
            format_types=["docx"], title="Report",
        )
        assert es.file_count == 1
        assert es.sections == []
        assert es.tables_count == 0
        assert es.charts_count == 0
        assert es.key_topics == []
        assert es.word_count == 0
        assert es.languages == []
        assert es.extraction_status == "success"
        assert es.warnings == []

    def test_create_with_all_fields(self):
        es = ExtractionSummary(
            file_count=2, total_pages=50,
            format_types=["docx", "pdf"], title="Annual Report",
            sections=[SectionSummary(title="Intro", page_range="1-5")],
            tables_count=3, charts_count=2,
            key_topics=["market", "revenue"], word_count=10000,
            languages=["zh", "en"],
            extraction_status="partial",
            warnings=["Table on page 12 could not be parsed"],
        )
        assert es.file_count == 2
        assert len(es.sections) == 1
        assert es.extraction_status == "partial"


class TestExtractionResult:
    def test_create_with_required_fields(self):
        er = ExtractionResult(
            title="Test Report",
            sections=[],
            tables=[],
            key_topics=[],
            metadata={},
            summary=None,
        )
        assert er.title == "Test Report"
        assert er.sections == []
        assert er.tables == []
        assert er.key_topics == []
        assert er.metadata == {}
        assert er.summary is None

    def test_create_with_all_fields(self):
        from src.content.content_orchestrator import ContentSection, SectionType
        section = ContentSection(
            id="sec_0", title="Overview", content="text",
            order=0, type=SectionType.BODY,
        )
        er = ExtractionResult(
            title="Report",
            sections=[section],
            tables=[[["A", "B"], ["1", "2"]]],
            key_topics=["market"],
            metadata={"format": "docx", "page_count": 10},
            summary=ExtractionSummary(
                file_count=1, total_pages=10,
                format_types=["docx"], title="Report",
            ),
        )
        assert len(er.sections) == 1
        assert len(er.tables) == 1
        assert er.metadata["format"] == "docx"
        assert er.summary is not None


class TestDataParserABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            DataParser()

    def test_subclass_must_implement_parse(self):
        class IncompleteParser(DataParser):
            pass

        with pytest.raises(TypeError):
            IncompleteParser()

    def test_subclass_with_parse_works(self):
        class ConcreteParser(DataParser):
            def parse(self, file_path: str) -> ExtractionResult:
                return ExtractionResult(
                    title="", sections=[], tables=[],
                    key_topics=[], metadata={}, summary=None,
                )

        parser = ConcreteParser()
        result = parser.parse("test.docx")
        assert isinstance(result, ExtractionResult)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/adjustment/test_extraction_types.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.core.adjustment.extraction_types'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/core/adjustment/extraction_types.py
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.content.content_orchestrator import ContentSection


@dataclass
class SectionSummary:
    title: str
    page_range: str
    content_preview: str = ""
    has_table: bool = False
    has_chart: bool = False


@dataclass
class ExtractionSummary:
    file_count: int
    total_pages: int
    format_types: List[str]
    title: Optional[str]
    sections: List[SectionSummary] = field(default_factory=list)
    tables_count: int = 0
    charts_count: int = 0
    key_topics: List[str] = field(default_factory=list)
    word_count: int = 0
    languages: List[str] = field(default_factory=list)
    extraction_status: str = "success"
    warnings: List[str] = field(default_factory=list)


@dataclass
class ExtractionResult:
    title: str
    sections: List[ContentSection]
    tables: List[List[List[str]]]
    key_topics: List[str]
    metadata: Dict[str, Any]
    summary: Optional[ExtractionSummary] = None


class DataParser(ABC):
    @abstractmethod
    def parse(self, file_path: str) -> ExtractionResult:
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/adjustment/test_extraction_types.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/adjustment/extraction_types.py tests/unit/adjustment/test_extraction_types.py
git commit -m "feat: add ExtractionResult, ExtractionSummary, SectionSummary, DataParser ABC"
```

---

## Task 2: DocxDataParser

**Files:**
- Create: `src/core/adjustment/ppt_input_adapter.py` (add DocxDataParser + PptInputAdapter stub)
- Test: `tests/unit/adjustment/test_ppt_input_adapter.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/adjustment/test_ppt_input_adapter.py
import os
import tempfile
import pytest

from src.core.adjustment.ppt_input_adapter import DocxDataParser, PptInputAdapter
from src.core.adjustment.extraction_types import ExtractionResult
from src.content.content_orchestrator import ContentSection, SectionType


def _create_docx_with_headings(path, paragraphs):
    """Create a docx file with given paragraphs. Each tuple is (style, text)."""
    from docx import Document
    doc = Document()
    for style, text in paragraphs:
        doc.add_paragraph(text, style=style)
    doc.save(path)


def _create_docx_with_tables(path, rows_data):
    """Create a docx file with a table."""
    from docx import Document
    doc = Document()
    table = doc.add_table(rows=len(rows_data), cols=len(rows_data[0]))
    for i, row in enumerate(rows_data):
        for j, cell in enumerate(row):
            table.rows[i].cells[j].text = cell
    doc.save(path)


class TestDocxDataParser:
    def test_parse_with_headings_creates_sections(self, tmp_path):
        docx_path = str(tmp_path / "test.docx")
        _create_docx_with_headings(docx_path, [
            ("Heading 1", "Introduction"),
            ("Normal", "This is the intro paragraph."),
            ("Heading 1", "Market Analysis"),
            ("Normal", "The market is growing."),
        ])
        parser = DocxDataParser()
        result = parser.parse(docx_path)
        assert isinstance(result, ExtractionResult)
        assert len(result.sections) == 2
        assert result.sections[0].title == "Introduction"
        assert result.sections[1].title == "Market Analysis"
        assert "intro paragraph" in result.sections[0].points[0]

    def test_parse_without_headings_creates_single_section(self, tmp_path):
        docx_path = str(tmp_path / "test.docx")
        _create_docx_with_headings(docx_path, [
            ("Normal", "First paragraph."),
            ("Normal", "Second paragraph."),
        ])
        parser = DocxDataParser()
        result = parser.parse(docx_path)
        assert len(result.sections) == 1
        assert result.sections[0].title == ""
        assert "First paragraph" in result.sections[0].content

    def test_parse_extracts_tables(self, tmp_path):
        docx_path = str(tmp_path / "test.docx")
        _create_docx_with_tables(docx_path, [
            ["Name", "Value"],
            ["Revenue", "$10B"],
        ])
        parser = DocxDataParser()
        result = parser.parse(docx_path)
        assert len(result.tables) == 1
        assert result.tables[0][0] == ["Name", "Value"]
        assert result.tables[0][1] == ["Revenue", "$10B"]

    def test_parse_metadata_includes_format(self, tmp_path):
        docx_path = str(tmp_path / "test.docx")
        _create_docx_with_headings(docx_path, [("Normal", "text")])
        parser = DocxDataParser()
        result = parser.parse(docx_path)
        assert result.metadata["format"] == "docx"

    def test_parse_nonexistent_file_raises(self):
        parser = DocxDataParser()
        with pytest.raises(FileNotFoundError):
            parser.parse("/nonexistent/file.docx")

    def test_parse_empty_docx(self, tmp_path):
        docx_path = str(tmp_path / "empty.docx")
        from docx import Document
        Document().save(docx_path)
        parser = DocxDataParser()
        result = parser.parse(docx_path)
        assert result.sections == []
        assert result.tables == []
        assert result.title == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/adjustment/test_ppt_input_adapter.py -v`
Expected: FAIL — `ImportError: cannot import name 'DocxDataParser'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/core/adjustment/ppt_input_adapter.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.adjustment.extraction_types import DataParser, ExtractionResult, ExtractionSummary, SectionSummary
from src.content.content_orchestrator import ContentSection, SectionType


class DocxDataParser(DataParser):
    def parse(self, file_path: str) -> ExtractionResult:
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        import docx
        doc = docx.Document(file_path)

        sections: List[ContentSection] = []
        current_section: Optional[ContentSection] = None
        for para in doc.paragraphs:
            if para.style.name.startswith("Heading"):
                current_section = ContentSection(
                    id=f"sec_{len(sections)}",
                    title=para.text.strip(),
                    content="",
                    order=len(sections),
                    type=SectionType.BODY,
                    points=[],
                )
                sections.append(current_section)
            elif current_section and para.text.strip():
                current_section.points.append(para.text.strip())

        if not sections:
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            if text:
                sections = [ContentSection(
                    id="sec_0", title="", content=text,
                    order=0, type=SectionType.BODY, points=[],
                )]

        tables: List[List[List[str]]] = []
        for table in doc.tables:
            rows = [[cell.text for cell in row.cells] for row in table.rows]
            tables.append(rows)

        title = self._detect_title(doc, sections)
        key_topics = self._extract_topics(sections)

        return ExtractionResult(
            title=title,
            sections=sections,
            tables=tables,
            key_topics=key_topics,
            metadata={
                "format": "docx",
                "para_count": len(doc.paragraphs),
                "table_count": len(doc.tables),
            },
            summary=None,
        )

    def _detect_title(self, doc, sections: List[ContentSection]) -> str:
        if sections and sections[0].title:
            return sections[0].title
        for para in doc.paragraphs:
            if para.style.name.startswith("Heading 1") and para.text.strip():
                return para.text.strip()
        return ""

    def _extract_topics(self, sections: List[ContentSection]) -> List[str]:
        return [s.title for s in sections if s.title]


class PptInputAdapter:
    def __init__(self):
        self._parsers: Dict[str, DataParser] = {
            ".docx": DocxDataParser(),
        }

    def extract(self, file_paths: List[str]) -> ExtractionResult:
        results: List[ExtractionResult] = []
        for fp in file_paths:
            ext = Path(fp).suffix.lower()
            parser = self._parsers.get(ext)
            if parser:
                results.append(parser.parse(fp))
            else:
                results.append(self._fallback_parse(fp))
        return self._merge(results)

    def _fallback_parse(self, file_path: str) -> ExtractionResult:
        return ExtractionResult(
            title=Path(file_path).stem,
            sections=[],
            tables=[],
            key_topics=[],
            metadata={"format": "unknown", "path": file_path},
            summary=None,
        )

    def _merge(self, results: List[ExtractionResult]) -> ExtractionResult:
        if not results:
            return ExtractionResult(
                title="", sections=[], tables=[],
                key_topics=[], metadata={}, summary=None,
            )
        if len(results) == 1:
            return results[0]

        all_sections: List[ContentSection] = []
        all_tables: List[List[List[str]]] = []
        all_topics: List[str] = []
        merged_meta: Dict[str, Any] = {"formats": [], "file_count": len(results)}
        for r in results:
            all_sections.extend(r.sections)
            all_tables.extend(r.tables)
            all_topics.extend(r.key_topics)
            if r.metadata.get("format"):
                merged_meta["formats"].append(r.metadata["format"])

        title = results[0].title if results[0].title else ""

        return ExtractionResult(
            title=title,
            sections=all_sections,
            tables=all_tables,
            key_topics=all_topics,
            metadata=merged_meta,
            summary=None,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/adjustment/test_ppt_input_adapter.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/adjustment/ppt_input_adapter.py tests/unit/adjustment/test_ppt_input_adapter.py
git commit -m "feat: add DocxDataParser and PptInputAdapter stub"
```

---

## Task 3: PptInputAdapter.extract() and _merge()

**Files:**
- Modify: `src/core/adjustment/ppt_input_adapter.py`
- Modify: `tests/unit/adjustment/test_ppt_input_adapter.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/adjustment/test_ppt_input_adapter.py`:

```python
class TestPptInputAdapter:
    def test_extract_single_docx(self, tmp_path):
        docx_path = str(tmp_path / "test.docx")
        _create_docx_with_headings(docx_path, [
            ("Heading 1", "Title"),
            ("Normal", "Content here."),
        ])
        adapter = PptInputAdapter()
        result = adapter.extract([docx_path])
        assert result.title == "Title"
        assert len(result.sections) == 1

    def test_extract_multiple_docx_merges(self, tmp_path):
        path1 = str(tmp_path / "doc1.docx")
        path2 = str(tmp_path / "doc2.docx")
        _create_docx_with_headings(path1, [("Heading 1", "Part One"), ("Normal", "A")])
        _create_docx_with_headings(path2, [("Heading 1", "Part Two"), ("Normal", "B")])
        adapter = PptInputAdapter()
        result = adapter.extract([path1, path2])
        assert len(result.sections) == 2
        assert result.metadata["file_count"] == 2

    def test_extract_empty_list_returns_empty(self):
        adapter = PptInputAdapter()
        result = adapter.extract([])
        assert result.title == ""
        assert result.sections == []

    def test_extract_unsupported_format_fallback(self, tmp_path):
        unsupported = str(tmp_path / "data.xyz")
        with open(unsupported, "w") as f:
            f.write("some data")
        adapter = PptInputAdapter()
        result = adapter.extract([unsupported])
        assert result.metadata["format"] == "unknown"
        assert result.title == "data"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/adjustment/test_ppt_input_adapter.py::TestPptInputAdapter -v`
Expected: PASS (PptInputAdapter already implemented in Task 2) — if all pass, skip to Step 5

- [ ] **Step 3: (Only if any test fails) Write minimal implementation**

Fix the specific failing behavior.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/adjustment/test_ppt_input_adapter.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/adjustment/test_ppt_input_adapter.py
git commit -m "test: add PptInputAdapter.extract() and _merge() tests"
```

---

## Task 4: PdfDataParser

**Files:**
- Modify: `src/core/adjustment/ppt_input_adapter.py`
- Modify: `tests/unit/adjustment/test_ppt_input_adapter.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/adjustment/test_ppt_input_adapter.py`:

```python
from src.core.adjustment.ppt_input_adapter import PdfDataParser


def _create_pdf_with_text(path, text_pages):
    """Create a simple PDF with text on each page. text_pages: list of strings."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(path, pagesize=letter)
    for page_text in text_pages:
        c.drawString(72, 720, page_text)
        c.showPage()
    c.save()


class TestPdfDataParser:
    def test_parse_extracts_text(self, tmp_path):
        pdf_path = str(tmp_path / "test.pdf")
        _create_pdf_with_text(pdf_path, ["Introduction page", "Market data page"])
        parser = PdfDataParser()
        result = parser.parse(pdf_path)
        assert isinstance(result, ExtractionResult)
        assert result.metadata["format"] == "pdf"
        assert result.metadata["page_count"] == 2

    def test_parse_nonexistent_file_raises(self):
        parser = PdfDataParser()
        with pytest.raises(FileNotFoundError):
            parser.parse("/nonexistent/file.pdf")

    def test_parse_empty_pdf(self, tmp_path):
        pdf_path = str(tmp_path / "empty.pdf")
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
        c = canvas.Canvas(pdf_path, pagesize=letter)
        c.showPage()
        c.save()
        parser = PdfDataParser()
        result = parser.parse(pdf_path)
        assert result.metadata["format"] == "pdf"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/adjustment/test_ppt_input_adapter.py::TestPdfDataParser -v`
Expected: FAIL — `ImportError: cannot import name 'PdfDataParser'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/core/adjustment/ppt_input_adapter.py`:

```python
class PdfDataParser(DataParser):
    def parse(self, file_path: str) -> ExtractionResult:
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        sections: List[ContentSection] = []
        tables: List[List[List[str]]] = []
        total_pages = 0

        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                total_pages = len(pdf.pages)
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text() or ""
                    if text.strip():
                        sections.append(ContentSection(
                            id=f"sec_{i}",
                            title=f"Page {i + 1}",
                            content=text.strip(),
                            order=i,
                            type=SectionType.BODY,
                            points=[],
                        ))
                    page_tables = page.extract_tables()
                    for table in page_tables:
                        if table:
                            tables.append(table)
        except ImportError:
            try:
                from PyPDF2 import PdfReader
                reader = PdfReader(file_path)
                total_pages = len(reader.pages)
                for i, page in enumerate(reader.pages):
                    text = page.extract_text() or ""
                    if text.strip():
                        sections.append(ContentSection(
                            id=f"sec_{i}",
                            title=f"Page {i + 1}",
                            content=text.strip(),
                            order=i,
                            type=SectionType.BODY,
                            points=[],
                        ))
            except ImportError:
                pass

        key_topics = self._extract_topics(sections)

        return ExtractionResult(
            title=sections[0].title if sections else "",
            sections=sections,
            tables=tables,
            key_topics=key_topics,
            metadata={"format": "pdf", "page_count": total_pages},
            summary=None,
        )

    def _extract_topics(self, sections: List[ContentSection]) -> List[str]:
        return [s.title for s in sections if s.title and s.title != s.content[:20]]
```

Also register in `PptInputAdapter.__init__`:
```python
self._parsers: Dict[str, DataParser] = {
    ".docx": DocxDataParser(),
    ".pdf": PdfDataParser(),
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/adjustment/test_ppt_input_adapter.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/adjustment/ppt_input_adapter.py tests/unit/adjustment/test_ppt_input_adapter.py
git commit -m "feat: add PdfDataParser with pdfplumber/PyPDF2 fallback"
```

---

## Task 5: ExcelDataParser

**Files:**
- Modify: `src/core/adjustment/ppt_input_adapter.py`
- Modify: `tests/unit/adjustment/test_ppt_input_adapter.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/adjustment/test_ppt_input_adapter.py`:

```python
from src.core.adjustment.ppt_input_adapter import ExcelDataParser


def _create_xlsx_with_data(path, sheets_data):
    """Create xlsx with sheets_data: dict of {sheet_name: [[row1], [row2], ...]}."""
    import openpyxl
    wb = openpyxl.Workbook()
    first = True
    for name, rows in sheets_data.items():
        if first:
            ws = wb.active
            ws.title = name
            first = False
        else:
            ws = wb.create_sheet(title=name)
        for row in rows:
            ws.append(row)
    wb.save(path)


class TestExcelDataParser:
    def test_parse_creates_section_per_sheet(self, tmp_path):
        xlsx_path = str(tmp_path / "test.xlsx")
        _create_xlsx_with_data(xlsx_path, {
            "Revenue": [["Year", "Amount"], ["2023", "$10B"], ["2024", "$12B"]],
            "Growth": [["Metric", "Value"], ["CAGR", "5%"]],
        })
        parser = ExcelDataParser()
        result = parser.parse(xlsx_path)
        assert isinstance(result, ExtractionResult)
        assert len(result.sections) == 2
        assert result.sections[0].title == "Revenue"
        assert result.sections[1].title == "Growth"

    def test_parse_extracts_tables(self, tmp_path):
        xlsx_path = str(tmp_path / "test.xlsx")
        _create_xlsx_with_data(xlsx_path, {
            "Data": [["A", "B"], ["1", "2"]],
        })
        parser = ExcelDataParser()
        result = parser.parse(xlsx_path)
        assert len(result.tables) == 1
        assert result.tables[0][0] == ["A", "B"]

    def test_parse_nonexistent_file_raises(self):
        parser = ExcelDataParser()
        with pytest.raises(FileNotFoundError):
            parser.parse("/nonexistent/file.xlsx")

    def test_parse_empty_workbook(self, tmp_path):
        xlsx_path = str(tmp_path / "empty.xlsx")
        import openpyxl
        wb = openpyxl.Workbook()
        wb.save(xlsx_path)
        parser = ExcelDataParser()
        result = parser.parse(xlsx_path)
        assert result.metadata["format"] == "xlsx"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/adjustment/test_ppt_input_adapter.py::TestExcelDataParser -v`
Expected: FAIL — `ImportError: cannot import name 'ExcelDataParser'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/core/adjustment/ppt_input_adapter.py`:

```python
class ExcelDataParser(DataParser):
    def parse(self, file_path: str) -> ExtractionResult:
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        import openpyxl
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)

        sections: List[ContentSection] = []
        tables: List[List[List[str]]] = []

        for idx, ws_name in enumerate(wb.sheetnames):
            ws = wb[ws_name]
            rows: List[List[str]] = []
            for row in ws.iter_rows(values_only=True):
                str_row = [str(cell) if cell is not None else "" for cell in row]
                rows.append(str_row)

            if rows:
                tables.append(rows)
                content = "\n".join(" | ".join(r) for r in rows[:20])
                sections.append(ContentSection(
                    id=f"sec_{idx}",
                    title=ws_name,
                    content=content,
                    order=idx,
                    type=SectionType.BODY,
                    points=[],
                ))

        wb.close()

        return ExtractionResult(
            title=sections[0].title if sections else p.stem,
            sections=sections,
            tables=tables,
            key_topics=[s.title for s in sections if s.title],
            metadata={"format": "xlsx", "sheet_count": len(wb.sheetnames)},
            summary=None,
        )
```

Register in `PptInputAdapter.__init__`:
```python
".xlsx": ExcelDataParser(),
".xls": ExcelDataParser(),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/adjustment/test_ppt_input_adapter.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/adjustment/ppt_input_adapter.py tests/unit/adjustment/test_ppt_input_adapter.py
git commit -m "feat: add ExcelDataParser with per-sheet sections"
```

---

## Task 6: TextDataParser + CsvDataParser + JsonDataParser

**Files:**
- Modify: `src/core/adjustment/ppt_input_adapter.py`
- Modify: `tests/unit/adjustment/test_ppt_input_adapter.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/adjustment/test_ppt_input_adapter.py`:

```python
from src.core.adjustment.ppt_input_adapter import TextDataParser, CsvDataParser, JsonDataParser


class TestTextDataParser:
    def test_parse_creates_single_section(self, tmp_path):
        txt_path = str(tmp_path / "test.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("This is a test document.\nIt has two lines.")
        parser = TextDataParser()
        result = parser.parse(txt_path)
        assert len(result.sections) == 1
        assert "test document" in result.sections[0].content
        assert result.metadata["format"] == "txt"

    def test_parse_nonexistent_file_raises(self):
        parser = TextDataParser()
        with pytest.raises(FileNotFoundError):
            parser.parse("/nonexistent/file.txt")

    def test_parse_empty_file(self, tmp_path):
        txt_path = str(tmp_path / "empty.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("")
        parser = TextDataParser()
        result = parser.parse(txt_path)
        assert result.sections == []


class TestCsvDataParser:
    def test_parse_extracts_headers_and_rows(self, tmp_path):
        csv_path = str(tmp_path / "test.csv")
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            import csv
            writer = csv.writer(f)
            writer.writerow(["Name", "Value"])
            writer.writerow(["Revenue", "$10B"])
            writer.writerow(["Growth", "5%"])
        parser = CsvDataParser()
        result = parser.parse(csv_path)
        assert len(result.tables) == 1
        assert result.tables[0][0] == ["Name", "Value"]
        assert result.metadata["format"] == "csv"

    def test_parse_nonexistent_file_raises(self):
        parser = CsvDataParser()
        with pytest.raises(FileNotFoundError):
            parser.parse("/nonexistent/file.csv")


class TestJsonDataParser:
    def test_parse_array_of_objects(self, tmp_path):
        json_path = str(tmp_path / "test.json")
        import json
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump([
                {"name": "Revenue", "value": "$10B"},
                {"name": "Growth", "value": "5%"},
            ], f)
        parser = JsonDataParser()
        result = parser.parse(json_path)
        assert len(result.sections) == 2
        assert result.metadata["format"] == "json"

    def test_parse_nested_object(self, tmp_path):
        json_path = str(tmp_path / "nested.json")
        import json
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                "title": "Report",
                "sections": [
                    {"heading": "Intro", "text": "Hello"},
                    {"heading": "Data", "text": "Numbers"},
                ],
            }, f)
        parser = JsonDataParser()
        result = parser.parse(json_path)
        assert result.title == "Report" or result.title == ""
        assert result.metadata["format"] == "json"

    def test_parse_nonexistent_file_raises(self):
        parser = JsonDataParser()
        with pytest.raises(FileNotFoundError):
            parser.parse("/nonexistent/file.json")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/adjustment/test_ppt_input_adapter.py::TestTextDataParser tests/unit/adjustment/test_ppt_input_adapter.py::TestCsvDataParser tests/unit/adjustment/test_ppt_input_adapter.py::TestJsonDataParser -v`
Expected: FAIL — `ImportError: cannot import name 'TextDataParser'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/core/adjustment/ppt_input_adapter.py`:

```python
class TextDataParser(DataParser):
    def parse(self, file_path: str) -> ExtractionResult:
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        text = p.read_text(encoding="utf-8", errors="replace").strip()
        sections: List[ContentSection] = []
        if text:
            sections.append(ContentSection(
                id="sec_0",
                title=p.stem,
                content=text,
                order=0,
                type=SectionType.BODY,
                points=[],
            ))

        return ExtractionResult(
            title=p.stem,
            sections=sections,
            tables=[],
            key_topics=[],
            metadata={"format": "txt", "word_count": len(text.split())},
            summary=None,
        )


class CsvDataParser(DataParser):
    def parse(self, file_path: str) -> ExtractionResult:
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        import csv
        rows: List[List[str]] = []
        with open(file_path, "r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                rows.append(row)

        sections: List[ContentSection] = []
        if rows:
            content = "\n".join(" | ".join(r) for r in rows[:50])
            sections.append(ContentSection(
                id="sec_0",
                title=p.stem,
                content=content,
                order=0,
                type=SectionType.BODY,
                points=[],
            ))

        return ExtractionResult(
            title=p.stem,
            sections=sections,
            tables=[rows] if rows else [],
            key_topics=[rows[0]] if rows else [],
            metadata={"format": "csv", "row_count": len(rows)},
            summary=None,
        )


class JsonDataParser(DataParser):
    def parse(self, file_path: str) -> ExtractionResult:
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        import json
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        sections: List[ContentSection] = []
        tables: List[List[List[str]]] = []
        title = p.stem

        if isinstance(data, list):
            for i, item in enumerate(data):
                if isinstance(item, dict):
                    content = "\n".join(f"{k}: {v}" for k, v in item.items())
                    sections.append(ContentSection(
                        id=f"sec_{i}",
                        title=item.get("name", item.get("heading", f"Item {i + 1}")),
                        content=content,
                        order=i,
                        type=SectionType.BODY,
                        points=[],
                    ))
                else:
                    sections.append(ContentSection(
                        id=f"sec_{i}",
                        title=f"Item {i + 1}",
                        content=str(item),
                        order=i,
                        type=SectionType.BODY,
                        points=[],
                    ))
        elif isinstance(data, dict):
            title = data.get("title", p.stem)
            if "sections" in data and isinstance(data["sections"], list):
                for i, sec in enumerate(data["sections"]):
                    if isinstance(sec, dict):
                        sections.append(ContentSection(
                            id=f"sec_{i}",
                            title=sec.get("heading", sec.get("title", f"Section {i + 1}")),
                            content=sec.get("text", str(sec)),
                            order=i,
                            type=SectionType.BODY,
                            points=[],
                        ))
            else:
                content = "\n".join(f"{k}: {v}" for k, v in data.items())
                sections.append(ContentSection(
                    id="sec_0",
                    title=title,
                    content=content,
                    order=0,
                    type=SectionType.BODY,
                    points=[],
                ))

        return ExtractionResult(
            title=title,
            sections=sections,
            tables=tables,
            key_topics=[s.title for s in sections if s.title],
            metadata={"format": "json"},
            summary=None,
        )
```

Register in `PptInputAdapter.__init__`:
```python
".txt": TextDataParser(),
".md": TextDataParser(),
".csv": CsvDataParser(),
".json": JsonDataParser(),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/adjustment/test_ppt_input_adapter.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/adjustment/ppt_input_adapter.py tests/unit/adjustment/test_ppt_input_adapter.py
git commit -m "feat: add TextDataParser, CsvDataParser, JsonDataParser"
```

---

## Task 7: PptRequirement + PptRequirementExtractor

**Files:**
- Create: `src/core/adjustment/ppt_requirement_extractor.py`
- Create: `tests/unit/adjustment/test_ppt_requirement_extractor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/adjustment/test_ppt_requirement_extractor.py
import pytest
from src.core.adjustment.ppt_requirement_extractor import PptRequirement, PptRequirementExtractor
from src.core.adjustment.extraction_types import ExtractionResult
from src.content.content_orchestrator import ContentSection, SectionType


def _make_extraction(title="Test Report", sections=None, key_topics=None):
    return ExtractionResult(
        title=title,
        sections=sections or [],
        tables=[],
        key_topics=key_topics or [],
        metadata={},
        summary=None,
    )


class TestPptRequirement:
    def test_create_with_defaults(self):
        req = PptRequirement(topic="Market Analysis")
        assert req.topic == "Market Analysis"
        assert req.audience == "business_professional"
        assert req.focus == []
        assert req.page_count is None
        assert req.style == "professional"
        assert req.confirmed is False

    def test_create_with_all_fields(self):
        req = PptRequirement(
            topic="AI Trends",
            audience="technical",
            focus=["LLM", "Agents"],
            page_count=15,
            style="modern",
            confirmed=True,
        )
        assert req.audience == "technical"
        assert req.page_count == 15
        assert req.confirmed is True


class TestPptRequirementExtractorFromData:
    def test_extracts_topic_from_title(self):
        extraction = _make_extraction(title="2024 Market Report")
        extractor = PptRequirementExtractor()
        req = extractor.extract(extraction)
        assert req.topic == "2024 Market Report"

    def test_extracts_topic_from_key_topics_when_no_title(self):
        extraction = _make_extraction(title="", key_topics=["AI", "Cloud"])
        extractor = PptRequirementExtractor()
        req = extractor.extract(extraction)
        assert req.topic == "AI"

    def test_default_topic_when_empty(self):
        extraction = _make_extraction(title="", key_topics=[])
        extractor = PptRequirementExtractor()
        req = extractor.extract(extraction)
        assert req.topic == "未命名主题"

    def test_focus_from_key_topics_capped_at_5(self):
        extraction = _make_extraction(key_topics=["A", "B", "C", "D", "E", "F", "G"])
        extractor = PptRequirementExtractor()
        req = extractor.extract(extraction)
        assert len(req.focus) == 5

    def test_page_count_from_sections(self):
        sections = [
            ContentSection(id=f"s{i}", title=f"Sec{i}", content="x", order=i, type=SectionType.BODY)
            for i in range(5)
        ]
        extraction = _make_extraction(sections=sections)
        extractor = PptRequirementExtractor()
        req = extractor.extract(extraction)
        assert req.page_count == 10

    def test_page_count_minimum_3(self):
        extraction = _make_extraction(sections=[])
        extractor = PptRequirementExtractor()
        req = extractor.extract(extraction)
        assert req.page_count == 3


class TestPptRequirementExtractorFromDescription:
    def test_extracts_topic_from_description(self):
        extraction = _make_extraction(title="Report")
        extractor = PptRequirementExtractor()
        req = extractor.extract(extraction, user_description="做一个关于新能源汽车的PPT")
        assert "新能源" in req.topic or req.topic == "Report"

    def test_description_overrides_data_topic(self):
        extraction = _make_extraction(title="Old Title")
        extractor = PptRequirementExtractor()
        req = extractor.extract(extraction, user_description="做一个关于AI趋势的汇报PPT")
        assert req.topic != "Old Title" or req.focus != []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/adjustment/test_ppt_requirement_extractor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.core.adjustment.ppt_requirement_extractor'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/core/adjustment/ppt_requirement_extractor.py
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from src.core.adjustment.extraction_types import ExtractionResult


@dataclass
class PptRequirement:
    topic: str
    audience: str = "business_professional"
    focus: List[str] = field(default_factory=list)
    page_count: Optional[int] = None
    style: str = "professional"
    confirmed: bool = False


class PptRequirementExtractor:
    def extract(self, extraction: ExtractionResult,
                user_description: str = "") -> PptRequirement:
        if user_description:
            return self._from_description(extraction, user_description)
        return self._from_data(extraction)

    def _from_data(self, extraction: ExtractionResult) -> PptRequirement:
        topic = extraction.title
        if not topic:
            topic = extraction.key_topics[0] if extraction.key_topics else "未命名主题"

        focus = extraction.key_topics[:5]
        page_count = max(3, len(extraction.sections) * 2)

        return PptRequirement(
            topic=topic,
            focus=focus,
            page_count=page_count,
        )

    def _from_description(self, extraction: ExtractionResult,
                          desc: str) -> PptRequirement:
        topic = self._extract_topic_from_text(desc)
        if not topic:
            topic = extraction.title or (extraction.key_topics[0] if extraction.key_topics else "未命名主题")

        focus = extraction.key_topics[:5]
        page_count = max(3, len(extraction.sections) * 2)

        return PptRequirement(
            topic=topic,
            focus=focus,
            page_count=page_count,
        )

    def _extract_topic_from_text(self, text: str) -> str:
        patterns = [
            r"关于(.+?)(?:的|之)PPT",
            r"关于(.+?)(?:的|之)汇报",
            r"关于(.+?)(?:的|之)报告",
            r"(.+?)PPT",
            r"(.+?)汇报",
            r"(.+?)报告",
        ]
        for pattern in patterns:
            m = re.search(pattern, text)
            if m:
                return m.group(1).strip()
        return ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/adjustment/test_ppt_requirement_extractor.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/adjustment/ppt_requirement_extractor.py tests/unit/adjustment/test_ppt_requirement_extractor.py
git commit -m "feat: add PptRequirement and PptRequirementExtractor"
```

---

## Task 8: DataGap + PptDataSupplementer

**Files:**
- Create: `src/core/adjustment/ppt_data_supplementer.py`
- Create: `tests/unit/adjustment/test_ppt_data_supplementer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/adjustment/test_ppt_data_supplementer.py
import pytest
from src.core.adjustment.ppt_data_supplementer import DataGap, PptDataSupplementer
from src.core.adjustment.extraction_types import ExtractionResult
from src.core.adjustment.ppt_requirement_extractor import PptRequirement
from src.content.content_orchestrator import ContentSection, SectionType


def _make_extraction(title="Report", sections=None, key_topics=None):
    return ExtractionResult(
        title=title,
        sections=sections or [],
        tables=[],
        key_topics=key_topics or [],
        metadata={},
        summary=None,
    )


def _make_requirement(topic="Market", focus=None):
    return PptRequirement(
        topic=topic,
        focus=focus or ["market size", "competition"],
    )


class TestDataGap:
    def test_create_with_defaults(self):
        gap = DataGap(topic="Market Size", priority="critical", search_queries=["market size data"])
        assert gap.topic == "Market Size"
        assert gap.priority == "critical"
        assert gap.search_queries == ["market size data"]
        assert gap.search_results == []
        assert gap.filled is False

    def test_create_filled(self):
        gap = DataGap(
            topic="Revenue", priority="optional",
            search_queries=["revenue data"],
            search_results=["Revenue is $10B"],
            filled=True,
        )
        assert gap.filled is True


class TestPptDataSupplementerAnalyzeGaps:
    def test_identifies_missing_focus_areas(self):
        extraction = _make_extraction(key_topics=["market size"])
        requirement = _make_requirement(focus=["market size", "competition", "technology"])
        supplementer = PptDataSupplementer()
        gaps = supplementer.analyze_gaps(extraction, requirement)
        gap_topics = [g.topic for g in gaps]
        assert "competition" in gap_topics
        assert "technology" in gap_topics
        assert "market size" not in gap_topics

    def test_no_gaps_when_all_covered(self):
        extraction = _make_extraction(key_topics=["market size", "competition"])
        requirement = _make_requirement(focus=["market size", "competition"])
        supplementer = PptDataSupplementer()
        gaps = supplementer.analyze_gaps(extraction, requirement)
        assert gaps == []

    def test_gaps_have_search_queries(self):
        extraction = _make_extraction(key_topics=[])
        requirement = _make_requirement(focus=["market size"])
        supplementer = PptDataSupplementer()
        gaps = supplementer.analyze_gaps(extraction, requirement)
        assert len(gaps) == 1
        assert len(gaps[0].search_queries) > 0


class TestPptDataSupplementerSupplement:
    def test_supplement_fills_gaps_with_search_skill(self):
        gaps = [
            DataGap(topic="Market Size", priority="critical",
                    search_queries=["market size 2024"]),
        ]
        mock_skill = _MockSearchSkill(results={"market size 2024": "Market is $10B"})
        supplementer = PptDataSupplementer()
        result = supplementer.supplement(gaps, search_skill=mock_skill)
        assert result[0].filled is True
        assert len(result[0].search_results) > 0

    def test_supplement_skips_already_filled(self):
        gaps = [
            DataGap(topic="Market Size", priority="critical",
                    search_queries=["market size"], search_results=["data"],
                    filled=True),
        ]
        supplementer = PptDataSupplementer()
        result = supplementer.supplement(gaps, search_skill=None)
        assert result[0].filled is True
        assert len(result[0].search_results) == 1

    def test_supplement_without_search_skill(self):
        gaps = [
            DataGap(topic="Market Size", priority="critical",
                    search_queries=["market size"]),
        ]
        supplementer = PptDataSupplementer()
        result = supplementer.supplement(gaps, search_skill=None)
        assert result[0].filled is False


class _MockSearchSkill:
    def __init__(self, results):
        self._results = results

    def execute(self, **kwargs):
        query = kwargs.get("query", "")
        if query in self._results:
            return {"success": True, "data": {"results": [self._results[query]]}}
        return {"success": False, "data": {"results": []}}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/adjustment/test_ppt_data_supplementer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.core.adjustment.ppt_data_supplementer'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/core/adjustment/ppt_data_supplementer.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.core.adjustment.extraction_types import ExtractionResult
from src.core.adjustment.ppt_requirement_extractor import PptRequirement


@dataclass
class DataGap:
    topic: str
    priority: str
    search_queries: List[str]
    search_results: List[str] = field(default_factory=list)
    filled: bool = False


class PptDataSupplementer:
    def analyze_gaps(self, extraction: ExtractionResult,
                     requirement: PptRequirement) -> List[DataGap]:
        covered = set(extraction.key_topics)
        gaps: List[DataGap] = []
        for focus_area in requirement.focus:
            if focus_area not in covered:
                gaps.append(DataGap(
                    topic=focus_area,
                    priority="critical",
                    search_queries=[f"{focus_area} {requirement.topic}"],
                ))
        return gaps

    def supplement(self, gaps: List[DataGap],
                   search_skill=None) -> List[DataGap]:
        for gap in gaps:
            if gap.filled:
                continue
            if search_skill:
                results = search_skill.execute(query=gap.search_queries[0], max_results=5)
                if results and results.get("success"):
                    data = results.get("data", {})
                    search_results = data.get("results", [])
                    if search_results:
                        gap.search_results = search_results
                        gap.filled = True
        return gaps
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/adjustment/test_ppt_data_supplementer.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/adjustment/ppt_data_supplementer.py tests/unit/adjustment/test_ppt_data_supplementer.py
git commit -m "feat: add DataGap and PptDataSupplementer"
```

---

## Task 9: Add PPT_GENERATION to IntentType

**Files:**
- Modify: `src/core/intent_types.py:33-42`
- Create: `tests/unit/core/test_intent_types_ppt.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/core/test_intent_types_ppt.py
import pytest
from src.core.intent_types import IntentType


class TestIntentTypePptGeneration:
    def test_ppt_generation_exists(self):
        assert hasattr(IntentType, "PPT_GENERATION")

    def test_ppt_generation_value(self):
        assert IntentType.PPT_GENERATION.value == "ppt_generation"

    def test_intent_type_count(self):
        assert len(IntentType) == 9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/core/test_intent_types_ppt.py -v`
Expected: FAIL — `AttributeError: PPT_GENERATION` or `AssertionError: 8 != 9`

- [ ] **Step 3: Write minimal implementation**

In `src/core/intent_types.py`, add after line 42:

```python
    PPT_GENERATION = "ppt_generation"  # PPT generation task
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/core/test_intent_types_ppt.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/intent_types.py tests/unit/core/test_intent_types_ppt.py
git commit -m "feat: add PPT_GENERATION to IntentType enum"
```

---

## Task 10: Add 3 New States to ConversationStateMachine

**Files:**
- Modify: `src/core/dialogue/state_machine.py:20-29` (add states)
- Modify: `src/core/dialogue/state_machine.py:45-92` (add transitions)
- Modify: `src/core/dialogue/state_machine.py:278-296` (add suggest_next cases)
- Create: `tests/unit/dialogue/test_state_machine_ppt_states.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/dialogue/test_state_machine_ppt_states.py
import pytest
from src.core.dialogue.state_machine import (
    ConversationState, ConversationStateMachine, InvalidTransitionError,
)
from src.core.dialogue.sub_intent import ReadinessLevel


class TestNewConversationStates:
    def test_data_extracted_state_exists(self):
        assert hasattr(ConversationState, "DATA_EXTRACTED")
        assert ConversationState.DATA_EXTRACTED.value == "data_extracted"

    def test_requirement_confirm_state_exists(self):
        assert hasattr(ConversationState, "REQUIREMENT_CONFIRM")
        assert ConversationState.REQUIREMENT_CONFIRM.value == "requirement_confirm"

    def test_data_supplement_state_exists(self):
        assert hasattr(ConversationState, "DATA_SUPPLEMENT")
        assert ConversationState.DATA_SUPPLEMENT.value == "data_supplement"


class TestNewStateTransitions:
    def test_understanding_to_data_extracted(self):
        sm = ConversationStateMachine()
        sm.transition(ConversationState.DATA_EXTRACTED)
        assert sm.current_state == ConversationState.DATA_EXTRACTED

    def test_data_extracted_to_requirement_confirm(self):
        sm = ConversationStateMachine()
        sm.transition(ConversationState.DATA_EXTRACTED)
        sm.transition(ConversationState.REQUIREMENT_CONFIRM)
        assert sm.current_state == ConversationState.REQUIREMENT_CONFIRM

    def test_data_extracted_to_clarifying(self):
        sm = ConversationStateMachine()
        sm.transition(ConversationState.DATA_EXTRACTED)
        sm.transition(ConversationState.CLARIFYING)
        assert sm.current_state == ConversationState.CLARIFYING

    def test_data_extracted_to_cancelled(self):
        sm = ConversationStateMachine()
        sm.transition(ConversationState.DATA_EXTRACTED)
        sm.transition(ConversationState.CANCELLED)
        assert sm.current_state == ConversationState.CANCELLED

    def test_requirement_confirm_to_data_supplement(self):
        sm = ConversationStateMachine()
        sm.transition(ConversationState.DATA_EXTRACTED)
        sm.transition(ConversationState.REQUIREMENT_CONFIRM)
        sm.transition(ConversationState.DATA_SUPPLEMENT)
        assert sm.current_state == ConversationState.DATA_SUPPLEMENT

    def test_requirement_confirm_to_framework_confirm(self):
        sm = ConversationStateMachine()
        sm.transition(ConversationState.DATA_EXTRACTED)
        sm.transition(ConversationState.REQUIREMENT_CONFIRM)
        sm.transition(ConversationState.FRAMEWORK_CONFIRM)
        assert sm.current_state == ConversationState.FRAMEWORK_CONFIRM

    def test_requirement_confirm_to_clarifying(self):
        sm = ConversationStateMachine()
        sm.transition(ConversationState.DATA_EXTRACTED)
        sm.transition(ConversationState.REQUIREMENT_CONFIRM)
        sm.transition(ConversationState.CLARIFYING)
        assert sm.current_state == ConversationState.CLARIFYING

    def test_data_supplement_to_framework_confirm(self):
        sm = ConversationStateMachine()
        sm.transition(ConversationState.DATA_EXTRACTED)
        sm.transition(ConversationState.REQUIREMENT_CONFIRM)
        sm.transition(ConversationState.DATA_SUPPLEMENT)
        sm.transition(ConversationState.FRAMEWORK_CONFIRM)
        assert sm.current_state == ConversationState.FRAMEWORK_CONFIRM

    def test_data_supplement_to_clarifying(self):
        sm = ConversationStateMachine()
        sm.transition(ConversationState.DATA_EXTRACTED)
        sm.transition(ConversationState.REQUIREMENT_CONFIRM)
        sm.transition(ConversationState.DATA_SUPPLEMENT)
        sm.transition(ConversationState.CLARIFYING)
        assert sm.current_state == ConversationState.CLARIFYING

    def test_invalid_transition_data_extracted_to_executing(self):
        sm = ConversationStateMachine()
        sm.transition(ConversationState.DATA_EXTRACTED)
        with pytest.raises(InvalidTransitionError):
            sm.transition(ConversationState.EXECUTING)

    def test_data_extracted_self_loop(self):
        sm = ConversationStateMachine()
        sm.transition(ConversationState.DATA_EXTRACTED)
        sm.transition(ConversationState.DATA_EXTRACTED)
        assert sm.current_state == ConversationState.DATA_EXTRACTED

    def test_requirement_confirm_self_loop(self):
        sm = ConversationStateMachine()
        sm.transition(ConversationState.DATA_EXTRACTED)
        sm.transition(ConversationState.REQUIREMENT_CONFIRM)
        sm.transition(ConversationState.REQUIREMENT_CONFIRM)
        assert sm.current_state == ConversationState.REQUIREMENT_CONFIRM

    def test_data_supplement_self_loop(self):
        sm = ConversationStateMachine()
        sm.transition(ConversationState.DATA_EXTRACTED)
        sm.transition(ConversationState.REQUIREMENT_CONFIRM)
        sm.transition(ConversationState.DATA_SUPPLEMENT)
        sm.transition(ConversationState.DATA_SUPPLEMENT)
        assert sm.current_state == ConversationState.DATA_SUPPLEMENT


class TestNewStateSuggestNext:
    def test_suggest_next_from_data_extracted_returns_none(self):
        sm = ConversationStateMachine()
        sm.transition(ConversationState.DATA_EXTRACTED)
        result = sm.suggest_next(_mock_intent_state(ReadinessLevel.SUFFICIENT))
        assert result is None

    def test_suggest_next_from_requirement_confirm_sufficient(self):
        sm = ConversationStateMachine()
        sm.transition(ConversationState.DATA_EXTRACTED)
        sm.transition(ConversationState.REQUIREMENT_CONFIRM)
        result = sm.suggest_next(_mock_intent_state(ReadinessLevel.SUFFICIENT))
        assert result == ConversationState.DATA_SUPPLEMENT

    def test_suggest_next_from_data_supplement_sufficient(self):
        sm = ConversationStateMachine()
        sm.transition(ConversationState.DATA_EXTRACTED)
        sm.transition(ConversationState.REQUIREMENT_CONFIRM)
        sm.transition(ConversationState.DATA_SUPPLEMENT)
        result = sm.suggest_next(_mock_intent_state(ReadinessLevel.SUFFICIENT))
        assert result == ConversationState.FRAMEWORK_CONFIRM


class _MockIntentState:
    def __init__(self, readiness_level):
        self.readiness_level = readiness_level


def _mock_intent_state(level):
    return _MockIntentState(level)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/dialogue/test_state_machine_ppt_states.py -v`
Expected: FAIL — `AttributeError: DATA_EXTRACTED`

- [ ] **Step 3: Write minimal implementation**

In `src/core/dialogue/state_machine.py`, add 3 new states to `ConversationState` enum (after line 29):

```python
    DATA_EXTRACTED = "data_extracted"           # 数据已提取
    REQUIREMENT_CONFIRM = "requirement_confirm"  # 确认PPT需求
    DATA_SUPPLEMENT = "data_supplement"          # 补充数据缺口
```

Add to `VALID_TRANSITIONS` dict:

```python
ConversationState.DATA_EXTRACTED: [
    ConversationState.DATA_EXTRACTED,
    ConversationState.REQUIREMENT_CONFIRM,
    ConversationState.CLARIFYING,
    ConversationState.EXECUTING,
    ConversationState.CANCELLED,
],
ConversationState.REQUIREMENT_CONFIRM: [
    ConversationState.REQUIREMENT_CONFIRM,
    ConversationState.DATA_SUPPLEMENT,
    ConversationState.FRAMEWORK_CONFIRM,
    ConversationState.CLARIFYING,
    ConversationState.CANCELLED,
],
ConversationState.DATA_SUPPLEMENT: [
    ConversationState.DATA_SUPPLEMENT,
    ConversationState.FRAMEWORK_CONFIRM,
    ConversationState.CLARIFYING,
    ConversationState.CANCELLED,
],
```

Also add `ConversationState.DATA_EXTRACTED` to the `UNDERSTANDING` transitions list.

Add to `suggest_next()` method (after the FRAMEWORK_CONFIRM block):

```python
if self.current_state == ConversationState.DATA_EXTRACTED:
    return None

if self.current_state == ConversationState.REQUIREMENT_CONFIRM:
    if intent_state.readiness_level == ReadinessLevel.SUFFICIENT:
        return ConversationState.DATA_SUPPLEMENT
    return None

if self.current_state == ConversationState.DATA_SUPPLEMENT:
    if intent_state.readiness_level == ReadinessLevel.SUFFICIENT:
        return ConversationState.FRAMEWORK_CONFIRM
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/dialogue/test_state_machine_ppt_states.py -v`
Expected: All PASS

Also run existing state machine tests to verify no regressions:
Run: `pytest tests/unit/dialogue/ -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/dialogue/state_machine.py tests/unit/dialogue/test_state_machine_ppt_states.py
git commit -m "feat: add DATA_EXTRACTED, REQUIREMENT_CONFIRM, DATA_SUPPLEMENT states"
```

---

## Task 11: Full Test Suite Verification

- [ ] **Step 1: Run all new tests together**

Run: `pytest tests/unit/adjustment/test_extraction_types.py tests/unit/adjustment/test_ppt_input_adapter.py tests/unit/adjustment/test_ppt_requirement_extractor.py tests/unit/adjustment/test_ppt_data_supplementer.py tests/unit/core/test_intent_types_ppt.py tests/unit/dialogue/test_state_machine_ppt_states.py -v`
Expected: All PASS

- [ ] **Step 2: Run full existing test suite to check for regressions**

Run: `pytest tests/unit/adjustment/ tests/unit/dialogue/ -v`
Expected: All PASS (no regressions)

- [ ] **Step 3: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: resolve any test regressions from new components"
```
