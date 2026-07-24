# PPT Data-Driven Generation Pipeline Design

> v2.0 — 2026-07-08 — Audited against real codebase (130K+ LOC)

## 1. Problem

Current pipeline is **research-driven**: user describes a topic → system researches → generates PPT.
New requirement: user provides **existing data** (Word/PDF/Excel/text/etc.) → system extracts, confirms intent, supplements gaps, generates PPT.

Core challenges:
- User data can be any format, any size (1 page to 100+ pages)
- Cannot display full extracted data in frontend
- Must confirm to user "I've read and understood your data"
- Then enter dialogue — first figure out what user wants (not assume PPT), then proceed

## 2. Design Principle

**Extract full, feedback summary, dialogue-first, intent-routed.**

- Extract ALL data into backend session context
- Feedback a concise SUMMARY to user (not raw data)
- Enter dialogue: system asks "您想基于这份材料做什么？" (NOT assuming PPT)
- Route based on intent: PPT → PPT flow; Word → Word flow; analysis → analysis flow
- For PPT: clarify requirements until sufficient (no round limit)
- Supplement data gaps automatically first, prompt user if needed

## 3. Flow (Mapped to Real Endpoints)

### 3.1 Current Upload Flow (what already exists)

```
Frontend ChatInput.tsx (line 174): user attaches files
    │
    ▼ api.uploadFiles(attachments)                    → POST /api/v1/upload (main.py:750)
    │  Returns: {session_id, files: [{id, filename, size, type, path}]}
    │  Files saved to data/uploads/, NO parsing
    │
    ▼ api.startResearch(input, undefined, llmConfig, fileIds)
    │  → POST /api/v1/research/start (main.py:223)
    │  ⚠️ BUG: backend start_research does NOT accept file_ids!
    │     Only quick_start (main.py:355) accepts file_ids (PDF-only)
    │     fileIds parameter is silently dropped
```

### 3.2 New Flow (extends existing, fixes gap)

```
Frontend ChatInput.tsx: user attaches files + types message
    │
    ▼ api.uploadFiles(attachments)                    → POST /api/v1/upload (EXISTING, unchanged)
    │  Returns: {session_id, files: [{id, filename, size, type, path}]}
    │
    ▼ api.startResearch(input, fileIds, llmConfig)   → POST /api/v1/research/start (MODIFIED)
    │  NEW: Add file_ids parameter to start_research (mirrors quick_start pattern)
    │  If file_ids present:
    │    1. Read files from data/uploads/
    │    2. PptInputAdapter.extract(file_paths) → ExtractionResult
    │    3. Store ExtractionResult in session['research_context']['extraction_result']
    │    4. Set state = DATA_EXTRACTED
    │    5. Return ExtractionSummary in response
    │  If no file_ids:
    │    1. Existing behavior (UNDERSTANDING state, research-driven)
    │
    ▼ EXISTING DIALOGUE via /api/v1/research/interact (main.py:444)
    │  System message: "已读取您的文档，共X页/Y节/Z表。主要涵盖：..."
    │  System asks: "您想基于这份材料做什么？"
    │  _llm_converse() handles response, routes by intent
    │
    ▼ INTENT ROUTING (within _handle_user_message, research_api.py:335)
    │  SemanticIntentAnalyzer.analyze_async() → DeepIntentResult
    │  IntentType already covers: RESEARCH, IMPLEMENTATION, INVESTIGATION, EVALUATION, FIX, OPEN_ENDED, CLARIFICATION, FORENSIC_ANALYSIS
    │  NEW: Add PPT_GENERATION to IntentType (src/core/intent_types.py)
    │  If intent = PPT_GENERATION → transition to REQUIREMENT_CONFIRM
    │  If intent = other → existing pipeline routing
    │
    ▼ REQUIREMENT_CONFIRM → DATA_SUPPLEMENT → FRAMEWORK_CONFIRM → ...
    └─ (see §4 for state details)
```

**Key decision**: Do NOT create new `/api/v1/ppt/*` endpoints. Extend existing `/api/v1/research/start` to accept `file_ids` (like `quick_start` already does), and handle extraction + dialogue within the existing interact flow. This minimizes frontend changes and leverages the existing chat-based UI.

## 4. State Machine Changes

### 4.1 Current States (state_machine.py:20-29)

```python
class ConversationState(Enum):
    UNDERSTANDING = "understanding"
    CLARIFYING = "clarifying"
    FRAMEWORK_CONFIRM = "framework_confirm"
    EXECUTING = "executing"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    PREVIEWING = "previewing"
    COMPLETED = "completed"
```

### 4.2 New States

| New State | Value | Description | Entry | Exit |
|-----------|-------|-------------|-------|------|
| `DATA_EXTRACTED` | `"data_extracted"` | Files uploaded and parsed, summary sent | Files with file_ids processed | User sends first message |
| `REQUIREMENT_CONFIRM` | `"requirement_confirm"` | Confirming PPT requirements | Intent = PPT_GENERATION | Requirements sufficient |
| `DATA_SUPPLEMENT` | `"data_supplement"` | Supplementing missing data | Gaps identified | All critical gaps filled |

### 4.3 Modified Transitions

```python
VALID_TRANSITIONS = {
    "UNDERSTANDING": ["UNDERSTANDING", "CLARIFYING", "EXECUTING", "FRAMEWORK_CONFIRM", "DATA_EXTRACTED", "CANCELLED"],
    "DATA_EXTRACTED": ["DATA_EXTRACTED", "REQUIREMENT_CONFIRM", "CLARIFYING", "EXECUTING", "CANCELLED"],
    "REQUIREMENT_CONFIRM": ["REQUIREMENT_CONFIRM", "DATA_SUPPLEMENT", "FRAMEWORK_CONFIRM", "CLARIFYING", "CANCELLED"],
    "DATA_SUPPLEMENT": ["DATA_SUPPLEMENT", "FRAMEWORK_CONFIRM", "CLARIFYING", "CANCELLED"],
    # ... all existing transitions preserved ...
}
```

### 4.4 Code Locations That Need Updates

| File | Line(s) | What to Change |
|------|---------|----------------|
| `src/core/dialogue/state_machine.py:20-29` | ConversationState enum | Add 3 new members |
| `src/core/dialogue/state_machine.py:45-92` | VALID_TRANSITIONS | Add 3 new entries, update UNDERSTANDING |
| `src/core/dialogue/state_machine.py:278-296` | suggest_next() | Add cases for DATA_EXTRACTED, REQUIREMENT_CONFIRM, DATA_SUPPLEMENT |
| `src/api/research_api.py:761-774` | _sync_mode_with_state() | Add mode mappings for new states |
| `src/api/research_api.py:789` | _build_dialogue_context() | Add LLM guidance prompts for new states |
| `src/api/research_api.py:781` | _resolve_transition() | Add action→state mappings for new states |
| `src/api/main.py:530` | list_all_sessions() (status_map at lines 578-583) | Add display names for new states |
| `src/api/main.py:610` | get_research_detail() (status_map at lines 630-635) | Add display names for new states |

## 5. Extraction Summary Format

```python
@dataclass
class ExtractionSummary:
    file_count: int
    total_pages: int
    format_types: List[str]
    title: Optional[str]
    sections: List[SectionSummary]
    tables_count: int
    charts_count: int
    key_topics: List[str]
    word_count: int
    languages: List[str]
    extraction_status: str            # "success" | "partial" | "failed"
    warnings: List[str]

@dataclass
class SectionSummary:
    title: str
    page_range: str
    content_preview: str              # first 100 chars
    has_table: bool
    has_chart: bool
```

## 6. New Components

### 6.1 PptInputAdapter

**Location**: `src/core/adjustment/ppt_input_adapter.py`

**Based on**: `FileParser.parse_file()` pattern in `src/core/memory/knowledge/importer.py:334`
but with structured output instead of flat string.

```python
class PptInputAdapter:
    def __init__(self):
        self._parsers: Dict[str, DataParser] = {
            ".docx": DocxDataParser(),
            ".pdf": PdfDataParser(),
            ".xlsx": ExcelDataParser(),
            ".xls": ExcelDataParser(),
            ".txt": TextDataParser(),
            ".md": TextDataParser(),
            ".csv": CsvDataParser(),
            ".json": JsonDataParser(),
        }

    def extract(self, file_paths: List[str]) -> ExtractionResult:
        results = []
        for fp in file_paths:
            ext = Path(fp).suffix.lower()
            parser = self._parsers.get(ext)
            if parser:
                results.append(parser.parse(fp))
            else:
                results.append(self._fallback_parse(fp))
        return self._merge(results)
```

### 6.2 Parsers — Delta vs Existing Code

Each parser outputs `ExtractionResult`. Current `FileParser._parse_*` methods return `str` — we need structured output.

#### DocxDataParser

**Current**: `FileParser._parse_word()` (importer.py:542-562) — extracts paragraphs only, returns flat string.

**New**: Must also extract headings (via `para.style.name` starts with "Heading"), tables (via `doc.tables`), and detect structure.

```python
class DocxDataParser(DataParser):
    def parse(self, file_path: str) -> ExtractionResult:
        import docx
        doc = docx.Document(file_path)
        sections = []
        current_section = None
        for para in doc.paragraphs:
            if para.style.name.startswith("Heading"):
                current_section = ContentSection(
                    id=f"sec_{len(sections)}",
                    title=para.text.strip(),
                    content="", order=len(sections),
                    type=SectionType.BODY, points=[],
                )
                sections.append(current_section)
            elif current_section and para.text.strip():
                current_section.points.append(para.text.strip())
        # If no headings found, treat all paragraphs as single section
        if not sections:
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            sections = [ContentSection(id="sec_0", title="", content=text,
                                       order=0, type=SectionType.BODY, points=[])]
        # Extract tables
        tables = []
        for table in doc.tables:
            rows = [[cell.text for cell in row.cells] for row in table.rows]
            tables.append(rows)
        return ExtractionResult(
            title=self._detect_title(doc), sections=sections,
            tables=tables, key_topics=self._extract_topics(sections),
            metadata={"format": "docx", "para_count": len(doc.paragraphs),
                      "table_count": len(doc.tables)},
            summary=self._build_summary(sections, tables),
        )
```

#### PdfDataParser

**Current**: `FileParser._parse_pdf()` (importer.py:517-540) uses PyPDF2, text only, returns flat string.
**Current**: `AnnualReportParserSkill.execute()` (annual_report_parser.py:70-869) uses pdfplumber, extracts sections+tables+financial data, returns `Dict`.

**New**: Two-tier strategy:
1. If document is an annual report → wrap AnnualReportParserSkill output
2. Otherwise → use pdfplumber for text+tables, PyPDF2 for page count

```python
class PdfDataParser(DataParser):
    def parse(self, file_path: str) -> ExtractionResult:
        # Try pdfplumber first (better table extraction)
        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                pages = pdf.pages
                total_pages = len(pages)
                # Extract text + tables per page
                ...
        except ImportError:
            # Fallback to PyPDF2 (text only, no tables)
            ...
```

#### ExcelDataParser

**Current**: `FileParser._parse_excel()` (importer.py:564-601) — iterates rows, returns pipe-delimited string, NO header detection.

**New**: Each sheet becomes a ContentSection. First row treated as header if it looks like one (non-numeric, short strings).

#### TextDataParser

**Current**: `FileParser._parse_text()` (importer.py:397-410) — reads file as string.

**New**: LLM-based structuring. Send text to LLM with prompt "请将以下内容按主题分段，每段给出标题和要点". Parse LLM response into ContentSections. Falls back to single section if LLM unavailable.

#### CsvDataParser

**Current**: `FileParser._parse_csv()` (importer.py:459-515) — key-value pairs per row.

**New**: First row = headers. ContentSection per logical group.

#### JsonDataParser

**Current**: `FileParser._parse_json()` (importer.py:423-433) — flattens to text via `_json_to_text()`.

**New**: Schema detection. If array of objects → each object as section. If nested → flatten to sections.

### 6.3 PptRequirementExtractor

**NOT a reuse of SemanticIntentAnalyzer** — that handles research intent classification (IntentType enum), not PPT requirements.

SemanticIntentAnalyzer is used for the intent routing step ("is this PPT?"). PptRequirementExtractor handles the PPT-specific step ("what kind of PPT?").

```python
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
        return PptRequirement(
            topic=extraction.title or (extraction.key_topics[0] if extraction.key_topics else "未命名主题"),
            focus=extraction.key_topics[:5],
            page_count=max(3, len(extraction.sections) * 2),
        )

    def _from_description(self, extraction: ExtractionResult,
                          desc: str) -> PptRequirement:
        # LLM-based extraction of topic/audience/focus from user description
        ...
```

### 6.4 PptDataSupplementer

**Gap analysis is NEW** — `DataCollectionAgent` (data_collection_agent.py:36) does search, not gap analysis.

**Search step REUSES** `MultiSearchSkill` (via `execute(query=..., engines=..., max_results=...)`) + `WebScraperSkill` via `ConversationToolSet` (research_api.py:60-168).

```python
@dataclass
class DataGap:
    topic: str
    priority: str               # "critical" | "optional"
    search_queries: List[str]
    search_results: List[str] = field(default_factory=list)
    filled: bool = False

class PptDataSupplementer:
    def analyze_gaps(self, extraction: ExtractionResult,
                     requirement: PptRequirement) -> List[DataGap]:
        # Compare extraction sections vs. expected sections for a PPT on requirement.topic
        # Use LLM to identify missing areas
        ...

    def supplement(self, gaps: List[DataGap],
                    search_skill=None) -> List[DataGap]:
        for gap in gaps:
            if gap.filled:
                continue
            if search_skill:
                results = search_skill.execute(query=gap.search_queries[0], max_results=5)
                if results:
                    gap.search_results = results
                    gap.filled = True
        return gaps
```

## 7. API Changes (Minimal)

### Modified Endpoints

| Endpoint | File:Line | Change |
|----------|-----------|--------|
| `POST /api/v1/research/start` | main.py:223 | Add `file_ids: Optional[str] = Form(None)` parameter (same pattern as quick_start at line 355) |
| `POST /api/v1/research/interact` | main.py:444 | Handle DATA_EXTRACTED/REQUIREMENT_CONFIRM/DATA_SUPPLEMENT states in _handle_user_message |

### No New Endpoints

All PPT-specific flows are handled within the existing chat-based interact endpoint. The dialogue system already supports state-specific behavior via `_build_dialogue_context()` (research_api.py:789) and `_resolve_transition()` (research_api.py:781).

## 8. Session Context Schema

**Storage location**: `session['research_context']` (NOT `state_machine.context`).

The actual codebase stores operational data in `session['research_context']` (research_api.py:331), not in `state_machine.context`. The state_machine.context is barely used.

```python
# Added to session['research_context']:
{
    # Extraction phase
    "extraction_result": ExtractionResult,     # full extracted data (backend only)
    "extraction_summary": ExtractionSummary,   # for frontend display
    
    # Requirement phase  
    "ppt_requirement": PptRequirement,         # confirmed requirements
    "clarification_count": int,                # rounds of clarification (no limit)
    
    # Supplement phase
    "data_gaps": List[DataGap],                # identified gaps
    "supplementation_result": List[DataGap],   # after supplementation
    
    # Generation phase (PPT revision pipeline)
    "slide_data_list": List[Dict],             # from SlideDataBuilder
    "slide_outline": SlideOutline,             # from SlideOutlineBuilder
    "outline_page_index": int,                 # current page being confirmed
}
```

## 9. Frontend Interaction Flow

### Current Frontend (what exists)

- `ChatInput.tsx` (line 174): file attachment button, accepts `.pdf,.doc,.docx,.xls,.xlsx,.txt,.md,.csv`
- `useResearch.ts` (line 131 def, line 140 upload flow): uploads files then calls `startResearch(input, undefined, llmConfig, fileIds)`
- Chat interface shows text messages only — no special card components

### New Flow (minimal frontend changes)

```
1. User attaches files + types message (existing UI)
   → api.uploadFiles()                    → POST /api/v1/upload (UNCHANGED)
   → api.startResearch(input, fileIds, llmConfig)  → POST /api/v1/research/start (MODIFIED: now accepts file_ids)

2. Backend processes files, creates session in DATA_EXTRACTED state
   → Returns first system message as chat response:
     "已读取3个文件《2024年新能源市场报告》，共98页/7章节/12表/5图。主要涵盖：市场规模, 竞争格局, 技术趋势。您想基于这份材料做什么？"
   → Frontend displays this as a regular chat message (no new components needed)

3. User types intent → handled via /api/v1/research/interact (EXISTING)
   → If "做PPT" → system enters REQUIREMENT_CONFIRM
   → If "分析数据" → system enters existing analysis flow
   → All via chat messages, no new UI needed

4. Subsequent steps all via chat dialogue (existing chat UI)
```

**Key insight**: We don't need a new "ExtractionSummary card" component. The summary is delivered as a chat message. This avoids frontend changes and works with the existing chat UI.

## 10. Large File Handling

| Scenario | Strategy |
|----------|----------|
| 100+ page document | Extract structure (headings, tables) first; full text stored in session but not sent to frontend; summary only |
| Scanned PDF pages | Reuse `AnnualReportParserSkill`'s OCR detection + Vision LLM (annual_report_parser.py:70-869) |
| 50MB+ Excel file | Sample first 100 rows per sheet; summary statistics only |
| Multiple files | Merge by topic; cross-reference tables |
| Non-text content (images, diagrams) | Vision LLM for description; store as image references in ContentSection |

## 11. Reuse of Existing Components — Honest Assessment

| Component | Reuse Level | Reality |
|-----------|------------|---------|
| `ConversationStateMachine` | **Extend** | Add 3 new states + transitions + suggest_next logic |
| `SemanticIntentAnalyzer` | **Partial** | Used for intent classification (is this PPT?). Does NOT infer PPT requirements. |
| `DialogueIntentState` | **Cannot reuse** | Hardcoded readiness weights for research (topic=0.25, aspects=0.35...). PPT needs different scoring. New `PptReadinessState` needed. |
| `FileParser._parse_word()` | **Cannot reuse** | Returns flat string. No headings, no tables, no structure. Must rewrite. |
| `FileParser._parse_pdf()` | **Cannot reuse** | Uses PyPDF2, returns flat string. Must use pdfplumber for tables. |
| `FileParser._parse_excel()` | **Cannot reuse** | No header detection, returns pipe-delimited string. Must rewrite. |
| `AnnualReportParserSkill` | **Wrap** | Returns Dict with sections+tables. Need adapter to ExtractionResult. |
| `MultiSearchSkill` | **Reuse** | Directly usable for data supplementation via ConversationToolSet. Called via `execute(query=..., max_results=...)`, NOT `.search()`. |
| `WebScraperSkill` | **Reuse** | Directly usable via ConversationToolSet.scrape_url(). |
| `SlideDataBuilder` | **Reuse** | ContentSection → slide_data dict. Directly reusable. |
| `SlideOutlineBuilder` | **Reuse** | slide_data_list → SlideOutline. Directly reusable. |
| `SlideDataStore` | **Reuse** | Persist slide_data. Directly reusable. |
| `HTMLToPPTConverter` | **Reuse** | slide_data_list → PPTX via _create_pptx_document(). |
| `PptRevisionService` | **Reuse** | Post-generation revision. Directly reusable. |
| `ConversationToolSet` | **Reuse** | web_search, news_search, scrape_url in dialogue. |
| `DataCollectionAgent` | **Partial** | Reuse for search execution, NOT for gap analysis (that's new). |

## 12. IntentType Extension

**File**: `src/core/intent_types.py`

Current `IntentType` does NOT include PPT generation:

```python
class IntentType(Enum):
    RESEARCH = "research"
    IMPLEMENTATION = "implementation"
    INVESTIGATION = "investigation"
    EVALUATION = "evaluation"
    FIX = "fix"
    OPEN_ENDED = "open_ended"
    CLARIFICATION = "clarification"
    FORENSIC_ANALYSIS = "forensic_analysis"
```

**Add**: `PPT_GENERATION = "ppt_generation"`

This allows `SemanticIntentAnalyzer` to classify user intent as "wants to make a PPT" and route to the PPT-specific flow.

## 13. Implementation Priority

| Phase | Components | Files to Create/Modify | Effort |
|-------|-----------|----------------------|--------|
| P0 | `ExtractionResult` + `ExtractionSummary` dataclasses | Create: `src/core/adjustment/extraction_types.py` | Low |
| P0 | `PptInputAdapter` + `DocxDataParser` | Create: `src/core/adjustment/ppt_input_adapter.py` | High |
| P0 | Extend `POST /research/start` with file_ids | Modify: `src/api/main.py:223` | Low |
| P1 | `PdfDataParser` (pdfplumber + AnnualReportParserSkill wrapper) | Create: in `ppt_input_adapter.py` | High |
| P1 | Add `PPT_GENERATION` to IntentType | Modify: `src/core/intent_types.py` | Low |
| P1 | Add 3 new states to ConversationStateMachine | Modify: `src/core/dialogue/state_machine.py` | Medium |
| P1 | Handle new states in research_api | Modify: `src/api/research_api.py` | Medium |
| P2 | `PptRequirementExtractor` | Create: `src/core/adjustment/ppt_requirement_extractor.py` | Medium |
| P2 | `PptDataSupplementer` | Create: `src/core/adjustment/ppt_data_supplementer.py` | Medium |
| P3 | `ExcelDataParser` + `TextDataParser` + `CsvDataParser` | Add to `ppt_input_adapter.py` | Medium |
| P4 | Large file handling (chunked processing) | Extend parsers | Medium |
| P5 | Full E2E integration test | Create: `tests/e2e/test_ppt_data_driven_e2e.py` | Medium |
