# PPT Revision Pipeline Design

**Date**: 2026-07-08
**Version**: v1.0
**Status**: Approved

## 1. Problem Statement

Current PPT generation pipeline has two critical gaps:

1. **No Slide Outline confirmation**: Users confirm research framework (which chapters), but not what each PPT page contains (data, charts, layout type). This leads to costly "做完再改" cycles.
2. **No PPT revision module**: The existing `RevisionService` only supports Markdown/Word. No code can locate or modify PPT slides, shapes, tables, or images.

Additional issue: Revision routing should reuse the existing intelligent intent analysis system (`RevisionIntentAnalyzer` — LLM-first + YAML fallback), not hardcode keyword patterns.

## 2. Architecture Decision: HTML-First Single Source

**HTML is the single source of truth.** PPT is a rendering output of HTML.

Three approaches were evaluated:

| Approach | Description | Pros | Cons |
|---|---|---|---|
| A: PPT-First | All revisions operate on pptx directly | Simple | HTML/PPT diverge; loses LayoutEngine dynamic layout |
| **B: HTML-First** | **HTML is truth source; PPT is output. Atomic edits dual-track (pptx+HTML), other levels modify HTML then re-render** | **Minimal change; preserves LayoutEngine; consistent state** | **Dual-write complexity for L1** |
| C: SlideData-First | slide_data is core model; HTML/PPT are render outputs | Cleanest data model | Requires major slide_data redesign |

**Chosen: Approach B (HTML-First)** — minimal pipeline change, preserves dynamic typography, HTML always consistent.

## 3. Pipeline Flow

### 3.1 Extended State Machine

New states added to `ConversationStateMachine`:

```
UNDERSTANDING → CLARIFYING → FRAMEWORK_CONFIRM → EXECUTING 
    → SLIDE_OUTLINE_CONFIRM → PPT_GENERATING → PREVIEWING 
    → PPT_REVISING → COMPLETED
```

New states:
- `SLIDE_OUTLINE_CONFIRM`: Per-page content confirmation before PPT generation
- `PPT_GENERATING`: PPT rendering in progress
- `PPT_REVISING`: PPT revision in progress (loops back to PREVIEWING)

### 3.2 Complete Flow

```
[1] UNDERSTANDING      — Intent understanding
[2] CLARIFYING         — Detail clarification
[3] FRAMEWORK_CONFIRM  — Research framework confirmation (existing)
[4] EXECUTING          — Data collection + analysis (existing)
[5] SLIDE_OUTLINE_CONFIRM — Per-page content confirmation (NEW)
[6] PPT_GENERATING     — PPT rendering (existing, now explicit state)
[7] PREVIEWING         — PPT preview (existing, expanded for PPT)
[8] PPT_REVISING       — PPT revision loop (NEW)
[9] COMPLETED          — Final export
```

At [5], user can modify outline (reorder, edit, delete pages). Loops back until confirmed.
At [7], user can request revision → [8] → loops back to [7] until confirmed.

## 4. Slide Outline Confirmation

### 4.1 Data Structure

```python
@dataclass
class SlideOutlineItem:
    page: int                    # Page number
    slide_type: str              # cover/toc/section_title/content/data/findings/end
    title: str                   # Page title
    data_summary: str            # Data summary (e.g. "6-row table + bar chart")
    chart_type: Optional[str]    # bar/pie/line/None
    key_points: List[str]        # Core content points (2-5 per page)
    data_source: Optional[str]   # Data source marker

@dataclass
class SlideOutline:
    task_id: str
    total_pages: int
    slides: List[SlideOutlineItem]
    confirmed: bool = False
```

### 4.2 Generation Process

1. After `ContentOrchestrator._generate_ppt_html()` completes, extract each `<section class="slide">`
2. Parse each slide for: title, slide_type, items/table_data/images
3. Assemble `SlideOutline` JSON
4. Push to frontend for visual card interface rendering

### 4.3 Frontend Card Interface

Each page rendered as a card showing:
- Page number, type icon, title, data summary, chart type indicator
- Actions: drag reorder, edit title/points, delete page, add page, change chart type
- User clicks "Confirm" → triggers PPT generation

### 4.4 API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/ppt/{task_id}/outline` | GET | Retrieve Slide Outline |
| `/api/v1/ppt/{task_id}/outline` | PUT | Modify and confirm Outline |
| `/api/v1/ppt/{task_id}/generate` | POST | Trigger PPT generation after confirmation |

## 5. PPT Revision Levels

### 5.1 Five-Level Strategy

Based on HTML-First architecture, revisions at deeper levels retreat further in the pipeline:

| Level | Scope | Mechanism | Time | Examples |
|---|---|---|---|---|
| **L1 Atomic** | Single shape text | Direct pptx edit + HTML sync | <1s | Change number, fix typo, change title |
| **L2 Element** | Chart/table/image | Regenerate element + replace shape + HTML sync | 2-5s | Swap chart type, replace image, change table data |
| **L3 Page** | Whole slide | Modify HTML → re-render slide → replace in pptx | 5-15s | Adjust layout, restyle, change KPI data |
| **L4 Structure** | Multiple slides | Modify HTML outline → full re-generate PPT | 30-60s | Add/delete pages, reorder, merge/split |
| **L5 Framework** | Entire report | Rollback to FRAMEWORK_CONFIRM → re-collect data | 10-30min | Redo chapters, change research direction |

### 5.2 L1: Atomic — Direct pptx + HTML Dual-Track

| Operation | pptx action | HTML sync |
|---|---|---|
| Change text | Modify shape.text_frame | Update corresponding HTML element text |
| Change number | Same | Same |
| Fix punctuation/case | Same | Same |
| Change title | Same | Same |

Implementation: `PptAtomicEditor` locates shape by slide_index + shape_index, modifies text directly. Then finds corresponding HTML section, updates text element.

### 5.3 L2: Element — Regenerate + Replace

| Operation | Mechanism |
|---|---|
| Swap chart type | SmartChartGenerator creates new chart → replace image shape → update HTML chart data |
| Change table data | Update HTML table → re-render slide → replace pptx slide |
| Replace image | ImageProvider fetches new image → replace image shape → update HTML img src |

Implementation: `PptElementEditor` calls SmartChartGenerator/ImageProvider, replaces shape in pptx, syncs HTML.

### 5.4 L3: Page — HTML → Re-render Single Slide

| Operation | Mechanism |
|---|---|
| Adjust layout/style | Modify HTML slide → LayoutEngine re-computes → SlideRenderer re-renders → replace pptx slide |
| Change content layout | Modify HTML structure → same pipeline |
| Change KPI values | Modify HTML KPI items → same pipeline |

Implementation: `PptPageEditor` modifies target HTML section, calls conversion pipeline for single slide, replaces slide in pptx.

**Key advantage**: LayoutEngine dynamically adjusts typography based on new content/height. No hardcoded dimensions.

### 5.5 L4: Structure — HTML → Full Re-generate

| Operation | Mechanism |
|---|---|
| Add/delete pages | Modify HTML outline (add/remove `<section class="slide">`) → full HTML→PPT pipeline |
| Reorder pages | Reorder HTML sections → same |
| Merge/split pages | Modify HTML structure → same |

Implementation: `PptStructureEditor` modifies HTML document structure, runs complete conversion pipeline.

### 5.6 L5: Framework — Pipeline Rollback

| Operation | Mechanism |
|---|---|
| Redo chapters | State machine rollback to `FRAMEWORK_CONFIRM` → re-execute data collection |
| Change direction | Same |

Implementation: Transition `ConversationState` back to `FRAMEWORK_CONFIRM`, re-run from step [3].

## 6. PPT Revision Module Architecture

### 6.1 Module Structure

```
src/core/adjustment/
├── ppt_revision_service.py      # PPT revision service (entry point)
├── ppt_revision_router.py       # Revision level routing (reuses RevisionIntentAnalyzer)
├── ppt_slide_locator.py         # PPT slide locator (page/title/content)
├── ppt_atomic_editor.py         # L1 atomic editor
├── ppt_element_editor.py        # L2 element editor
├── ppt_page_editor.py           # L3 page editor
├── ppt_structure_editor.py      # L4 structure editor
├── ppt_version_manager.py       # PPT version snapshot manager
└── ppt_revision_types.py        # PPT-specific revision types
```

### 6.2 PptRevisionService — Entry Point

```python
class PptRevisionService:
    def __init__(self, html_path, pptx_path, chart_generator, image_provider):
        self.router = PptRevisionRouter()
        self.locator = PptSlideLocator()
        self.atomic = PptAtomicEditor()
        self.element = PptElementEditor(chart_generator, image_provider)
        self.page = PptPageEditor()
        self.structure = PptStructureEditor()
        self.version_mgr = PptVersionManager()
    
    async def revise(self, request: PptRevisionRequest) -> PptRevisionResult:
        # 1. Snapshot current version
        self.version_mgr.snapshot(self.pptx_path)
        # 2. Route to revision level
        level = self.router.route_level(request)
        # 3. Execute revision
        result = await self._dispatch(level, request)
        # 4. Return result
        return result
    
    async def _dispatch(self, level, request):
        if level == "L1":
            return await self.atomic.edit(request)
        elif level == "L2":
            return await self.element.edit(request)
        elif level == "L3":
            return await self.page.edit(request)
        elif level == "L4":
            return await self.structure.edit(request)
        elif level == "L5":
            return await self._rollback_framework(request)
```

### 6.3 PptRevisionRouter — Intelligent Routing

**Reuses existing `RevisionIntentAnalyzer` (LLM-first + regex fallback). No hardcoded keywords.**

```python
class PptRevisionRouter:
    """PPT revision router — reuses RevisionIntentAnalyzer for intelligent intent analysis"""
    
    LEVEL_MAP = {
        # L1 Atomic: direct pptx edit
        RevisionOpType.REPLACE_TEXT: "L1",
        RevisionOpType.FIX_PUNCTUATION: "L1",
        RevisionOpType.CHANGE_CASE: "L1",
        RevisionOpType.UPDATE_TITLE: "L1",
        # L2 Element: regenerate element
        RevisionOpType.MODIFY_TABLE: "L2",
        RevisionOpType.MODIFY_CHART: "L2",
        RevisionOpType.ADD_ELEMENT: "L2",
        RevisionOpType.DELETE_ELEMENT: "L2",
        # L3 Page: HTML → re-render slide
        RevisionOpType.MODIFY: "L3",
        RevisionOpType.STYLE: "L3",
        # L4 Structure: HTML → full re-generate
        RevisionOpType.ADD: "L4",
        RevisionOpType.DELETE: "L4",
        RevisionOpType.MERGE: "L4",
        RevisionOpType.SPLIT: "L4",
        RevisionOpType.SWAP: "L4",
        RevisionOpType.REORDER: "L4",
        RevisionOpType.DEDUP: "L4",
        RevisionOpType.COPY: "L4",
        RevisionOpType.TRANSLATE: "L4",
    }
    
    def __init__(self):
        self.intent_analyzer = RevisionIntentAnalyzer()
    
    async def route(self, user_message: str, report: Report, ppt_context: Dict) -> PptRevisionRequest:
        # 1. Call existing RevisionIntentAnalyzer (LLM-first + regex fallback)
        analysis = await self.intent_analyzer.analyze(user_message, report)
        # 2. Extract action_type, map to PPT revision level
        if analysis.intents:
            action_type = analysis.intents[0].action_type
            level = self.LEVEL_MAP.get(action_type, "L3")
        else:
            level = "L3"
        # 3. Extract PPT location from analysis
        location = self._extract_ppt_location(analysis, ppt_context)
        # 4. Assemble request
        return PptRevisionRequest(level=level, intent=analysis, location=location)
```

### 6.4 YAML Extension

New section in `config/keyword_mappings.yaml` for PPT-specific regex fallback patterns:

```yaml
ppt_revision_intents:
  modify_slide:
    ppt_level: L3
    patterns:
      - "重新排版|调整布局|改排版|太挤|太松|排版不好"
      - "reformat|adjust layout|too cramped|too sparse"
  change_chart_type:
    ppt_level: L2
    patterns:
      - "换成饼图|改成柱状图|换折线图|改图表|换图表"
      - "change to pie|switch to bar|change chart type"
  replace_image:
    ppt_level: L2
    patterns:
      - "换图片|换配图|改图片|换插图"
      - "replace image|change image|swap image"
```

### 6.5 LLM Prompt Extension

Add PPT context section to existing `_REVISION_SYSTEM_PROMPT`:

```
PPT-specific context:
- Available PPT revision levels: L1 (atomic text change), L2 (chart/image/table swap), 
  L3 (page re-layout), L4 (add/delete/merge/split pages), L5 (framework rollback)
- When user refers to "第5页" or "slide 5", set target.slide_index = 4
- When user says "换饼图", map to modify_chart with parameters.chart_type = "pie"
- When user says "这页太挤了", map to modify with ppt_level = "L3"
```

### 6.6 PptSlideLocator — Three Location Strategies

| Strategy | Input | Mechanism |
|---|---|---|
| Page number | `"第5页"` / `slide_index=4` | Direct index access |
| Title match | `"市场规模"` | Find slide whose title shape text contains keyword |
| Content keyword | `"KPI"` | Find slide whose text content contains keyword (semantic match via `SectionLocator`) |

### 6.7 PptVersionManager — Complete Version Snapshots

- Before each revision: copy current pptx to `data/revisions/{task_id}/v{N}.pptx`
- Keep last 10 versions, delete oldest when exceeded
- Support rollback: `rollback(version=N)` → copy snapshot back to active path
- Store version metadata: `{version, timestamp, revision_level, user_message}`

### 6.8 HTML Sync Mechanism

For L1/L2 revisions, HTML must stay consistent with pptx:

- Maintain `slide_index → HTML section offset` mapping
- After modifying pptx shape, find corresponding HTML section, update text/data
- L3/L4 naturally modify HTML first then re-render, no extra sync needed
- If HTML sync fails: mark HTML as "dirty", auto-repair on next L3+ revision

## 7. Mixed-Mode Revision Interaction

### 7.1 Click-Select (Simple Operations)

Users interact directly on PPT preview page:

| Action | Trigger | Level | Example |
|---|---|---|---|
| Change text | Click text → edit popup | L1 | Edit title, number |
| Swap chart | Click chart → select type | L2 | Bar → Pie |
| Replace image | Click image → refresh | L2 | New illustration |
| Delete page | Page × button | L4 | Remove page |
| Add page | Between pages + button | L4 | Insert new page |
| Drag reorder | Drag page card | L4 | Adjust order |

### 7.2 Natural Language (Complex Operations)

User types in dialog box, `PptRevisionRouter` parses intent:

- Uses `RevisionIntentAnalyzer` (LLM-first, YAML regex fallback)
- Extracts page reference: `"第5页"` → slide_index
- Extracts operation type: matches RevisionOpType via LLM or keyword registry
- Assembles `PptRevisionRequest`

### 7.3 Flow

```
User on preview page:
  ├─ Click element → quick action panel → select action → execute
  │   (L1/L2 simple operations)
  │
  └─ Type natural language → RevisionRouter (via RevisionIntentAnalyzer) → confirm → execute
      (L3/L4/L5 complex operations)
```

Frontend displays:
- L1: Instant, no loading
- L2: 2-5s loading, "Updating chart..."
- L3: 5-15s loading, "Re-rendering page..."
- L4: 30-60s loading, "Re-generating PPT..."
- L5: Confirmation dialog "Need to re-collect data (~10-30min)", proceed after user confirms

## 8. API Endpoints Summary

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/ppt/{task_id}/outline` | GET | Get Slide Outline |
| `/api/v1/ppt/{task_id}/outline` | PUT | Modify and confirm Outline |
| `/api/v1/ppt/{task_id}/generate` | POST | Trigger PPT generation |
| `/api/v1/ppt/{task_id}/preview` | GET | Preview PPT |
| `/api/v1/ppt/{task_id}/revise` | POST | Submit revision request |
| `/api/v1/ppt/{task_id}/versions` | GET | Get version history |
| `/api/v1/ppt/{task_id}/rollback` | POST | Rollback to specified version |
| `/api/v1/ppt/{task_id}/export` | POST | Final export |
| `/api/v1/ppt/{task_id}/confirm` | POST | Confirm final version |

### Revision Request Format

```python
@dataclass
class PptRevisionRequest:
    task_id: str
    # Location (choose one)
    slide_index: Optional[int] = None
    slide_title: Optional[str] = None
    content_keyword: Optional[str] = None
    # Revision content
    revision_type: str = "modify"
    description: str = ""
    # L2 element-specific
    new_chart_type: Optional[str] = None
    new_data: Optional[Dict] = None
    # L1 atomic-specific
    target_field: Optional[str] = None
    new_value: Optional[str] = None
    # Internal (from RevisionIntentAnalyzer)
    intent_analysis: Optional[AnalysisResult] = None
    revision_level: Optional[str] = None
```

## 9. Error Handling

| Scenario | Handling |
|---|---|
| PPT corrupt after revision | Auto-rollback to previous version snapshot |
| L1 dual-write fails (pptx ok, HTML fails) | Keep pptx change, mark HTML dirty, auto-repair on next L3+ |
| L2 chart generation fails | Keep original chart, return failure reason |
| L3 single-slide render fails | Escalate to L4 full re-generate |
| L4 full re-generate fails | Rollback to previous version snapshot |
| L5 data collection fails | No impact on current PPT, return error info |
| Concurrent revision conflict | Optimistic lock: version number check, prompt user to refresh |

## 10. Edge Cases

| Scenario | Handling |
|---|---|
| User deletes all pages | Reject: must keep cover + end |
| User modifies cover page | L3: re-render cover |
| User changes KPI display value but not data | L1: change display only (data change → L5) |
| Revision exceeds 10 rounds | Prompt "建议重新确认框架", guide to L5 |
| Slide Outline data stale after confirmation | Mark outline as stale, prompt re-confirmation |
| PPT externally modified | Version mismatch, reject revision, prompt re-generation |

## 11. Testing Strategy

| Level | Test Content |
|---|---|
| Unit | PptSlideLocator, PptRevisionRouter routing, PptAtomicEditor text change, PptVersionManager snapshot/rollback |
| Integration | L1→verify pptx+HTML sync, L2→verify new chart, L3→verify layout, L4→verify full PPT |
| E2E | Full flow: framework confirm → data collection → outline confirm → PPT gen → preview → revise → confirm → export |
| Regression | After revision, 142 existing LayoutEngine/SlideRenderer tests still pass |

## 12. Performance Targets

| Operation | Target |
|---|---|
| L1 Atomic revision | < 1 second |
| L2 Element revision | < 5 seconds |
| L3 Page revision | < 15 seconds |
| L4 Structure revision | < 60 seconds |
| L5 Framework revision | < 30 minutes |
| Outline generation | < 3 seconds |
| Version snapshot | < 2 seconds |
| Version rollback | < 3 seconds |

## 13. Relationship with Existing RevisionService

`PptRevisionService` is an independent service, not inheriting `RevisionService`, but reusing:

- `RevisionOpType` enum (extended with PPT-specific ops in mapping)
- `RevisionIntentAnalyzer` for intelligent intent routing (LLM-first + YAML fallback)
- `KeywordRegistry` for PPT-specific regex fallback patterns
- `SectionLocator` semantic location logic (adapted for slide location)
- `SnapshotManager` pattern (adapted for PPT version snapshots)

No new RevisionOpType values needed — the 21 existing types cover all PPT revision scenarios through the LEVEL_MAP mapping.

## 14. Implementation Priority

| Phase | Scope | Priority |
|---|---|---|
| P0 | Slide Outline generation + confirmation API | High |
| P1 | PptRevisionService skeleton + PptVersionManager + PptSlideLocator | High |
| P1 | PptRevisionRouter (reuse RevisionIntentAnalyzer) | High |
| P2 | L1 Atomic editor (pptx direct edit + HTML sync) | High |
| P2 | L2 Element editor (chart/image swap) | Medium |
| P3 | L3 Page editor (HTML → single-slide re-render) | Medium |
| P3 | L4 Structure editor (HTML → full re-generate) | Medium |
| P4 | L5 Framework rollback (state machine transition) | Low |
| P4 | Frontend card interface for Outline | Medium |
| P4 | Frontend click-select interaction | Medium |
