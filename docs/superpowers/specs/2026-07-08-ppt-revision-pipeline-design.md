# PPT Revision Pipeline Design

**Date**: 2026-07-08
**Version**: v2.3
**Status**: Draft (post deep-review revision — 19 v1.0 + 22 v2.1 + 8 v2.2 issues fixed)

## 1. Problem Statement

Current PPT generation pipeline has two critical gaps:

1. **No Slide Outline confirmation**: Users confirm research framework (which chapters), but not what each PPT page contains (data, charts, layout type). This leads to costly "做完再改" cycles.
2. **No PPT revision module**: The existing `RevisionService` only supports Markdown/Word. No code can locate or modify PPT slides, shapes, tables, or images.

Additional issue: Revision routing should reuse the existing intelligent intent analysis system (`RevisionIntentAnalyzer` — LLM-first + YAML fallback), not hardcode keyword patterns.

## 2. Architecture Decision: SlideData-First Single Source

**slide_data is the single source of truth.** HTML and PPT are both rendering outputs of slide_data.

### 2.1 Why Not HTML-First (v1.0 choice, rejected after self-review)

HTML-First was rejected for three critical reasons:

1. **HTML↔pptx sync is infeasible** (P1): HTML is nested tags+CSS with no shape IDs. After L1 edits a pptx shape, finding the "corresponding HTML element" is unreliable. Long-term HTML/pptx divergence is inevitable.

2. **Outline data source is wrong** (P3): If HTML is truth source, Outline must be extracted from HTML. But Outline should be generated *before* HTML, from slide_data. Extracting from HTML then re-generating HTML after Outline edits is circular.

3. **HTML is not the real truth source** (P4): The actual pipeline is `ContentSection → HTML → slide_data → PPT`. HTML is an intermediate serialization format. slide_data (produced by `SlideElementParser`) is the structured data model that `SlideRenderer` consumes. Modifying HTML then re-parsing to get slide_data loses information (chart metadata, KPI detection results, template selection).

### 2.2 Three Approaches Re-evaluated

| Approach | Description | Pros | Cons |
|---|---|---|---|
| A: PPT-First | All revisions operate on pptx directly | Simple | Loses LayoutEngine dynamic layout; no structured data model |
| B: HTML-First | HTML is truth source; dual-track sync | Preserves LayoutEngine | Dual-write infeasible (P1); wrong data source for Outline (P3); HTML is not real truth (P4) |
| **C: SlideData-First** | **slide_data is core model; HTML/PPT are render outputs** | **Clean data model; no sync needed; Outline naturally from slide_data; preserves LayoutEngine** | **Requires slide_data persistence + SlideDataStore** |

**Chosen: Approach C (SlideData-First)** — eliminates dual-write, makes Outline extraction natural, preserves all pipeline metadata.

### 2.3 SlideData-First Architecture

```
ContentSection → slide_data_list (via SlideDataBuilder)
                      │
                      ├──► SlideOutline (for user confirmation)
                      │
                      ├──► HTML (render output, optional, for preview)
                      │
                      └──► PPT (render output, via LayoutEngine + SlideRenderer)
```

Key changes from v1.0:
- **New `SlideDataBuilder`**: Bypasses the HTML intermediate step by converting `ContentSection → slide_data` directly, eliminating the HTML round-trip. `SlideElementParser` (HTML→slide_data) is retained for the HTML preview path but is no longer the primary slide_data source. `SlideDataBuilder` must replicate the field mapping currently done by `SlideElementParser._build_slide_dict()` (slide_type, title, content, items, table_data, images, extra_tables, source_text) plus `TemplateSelector._enhance_slide_data()` (kpi_data, comparison_data, section_number, section_summary, insight_text).
- **New `SlideDataStore`**: Persists slide_data_list to `data/slide_data/{task_id}.json`. This is the truth source for all revisions.
- **No HTML sync needed**: L1/L2 edit slide_data + pptx directly. L3/L4 edit slide_data then re-render PPT. HTML is generated on-demand for preview only.
- **Outline from slide_data**: `SlideOutline` is a view/projection of slide_data_list, not a separate extraction step.

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

### 3.1.1 Valid Transitions (P6 fix)

```python
VALID_TRANSITIONS = {
    # Existing transitions (preserved from current ConversationStateMachine)
    ConversationState.UNDERSTANDING: [
        ConversationState.UNDERSTANDING,       # self-loop
        ConversationState.CLARIFYING,
        ConversationState.EXECUTING,
        ConversationState.FRAMEWORK_CONFIRM,
        ConversationState.CANCELLED,
    ],
    ConversationState.CLARIFYING: [
        ConversationState.CLARIFYING,          # self-loop
        ConversationState.FRAMEWORK_CONFIRM,
        ConversationState.CANCELLED,
    ],
    ConversationState.FRAMEWORK_CONFIRM: [
        ConversationState.FRAMEWORK_CONFIRM,   # self-loop
        ConversationState.EXECUTING,
        ConversationState.PREVIEWING,          # legacy: preview existing report before data collection (e.g. re-editing a previously completed report)
        ConversationState.CLARIFYING,
        ConversationState.CANCELLED,
    ],
    ConversationState.EXECUTING: [
        ConversationState.EXECUTING,           # self-loop
        ConversationState.PAUSED,
        ConversationState.PREVIEWING,
        ConversationState.COMPLETED,
        ConversationState.CANCELLED,
        ConversationState.CLARIFYING,          # fallback for requirement supplement
        ConversationState.FRAMEWORK_CONFIRM,   # user requests framework redesign
        ConversationState.SLIDE_OUTLINE_CONFIRM,  # NEW: data done → outline
    ],
    ConversationState.PAUSED: [
        ConversationState.PAUSED,              # self-loop
        ConversationState.EXECUTING,
        ConversationState.FRAMEWORK_CONFIRM,
        ConversationState.CANCELLED,
    ],
    ConversationState.CANCELLED: [
        ConversationState.CANCELLED,           # terminal
    ],
    # New states
    ConversationState.SLIDE_OUTLINE_CONFIRM: [
        ConversationState.SLIDE_OUTLINE_CONFIRM,  # self-loop (re-edit outline)
        ConversationState.EXECUTING,              # back to data collection
        ConversationState.PPT_GENERATING,         # outline confirmed → generate
        ConversationState.PAUSED,
        ConversationState.CANCELLED,
    ],
    ConversationState.PPT_GENERATING: [
        ConversationState.SLIDE_OUTLINE_CONFIRM,  # gen fail → back to outline
        ConversationState.PREVIEWING,             # gen success → preview
        ConversationState.PAUSED,
        ConversationState.CANCELLED,
    ],
    ConversationState.PREVIEWING: [
        ConversationState.PREVIEWING,          # self-loop
        ConversationState.PPT_REVISING,        # user requests revision
        ConversationState.COMPLETED,
        ConversationState.PAUSED,
        ConversationState.CANCELLED,
    ],
    ConversationState.PPT_REVISING: [
        ConversationState.PREVIEWING,             # revision done → preview
        ConversationState.SLIDE_OUTLINE_CONFIRM,  # user re-edits outline during revision; Outline is always projected from CURRENT slide_data_list (reflecting any L1/L2/L3 modifications already applied)
        ConversationState.PPT_GENERATING,         # L4 re-generate triggers re-render
        ConversationState.PAUSED,
        ConversationState.CANCELLED,
    ],
    ConversationState.COMPLETED: [
        ConversationState.COMPLETED,           # terminal
    ],
}
```

### 3.1.2 PPT_REVISING Sub-States (P9 fix)

`PPT_REVISING` carries a `revision_level` attribute so frontend can show appropriate loading:

| revision_level | Frontend feedback | Duration |
|---|---|---|
| L0 | Instant, show analysis result | <1s |
| L1 | Instant, no loading | <1s |
| L2 | "Updating element..." | 2-5s |
| L3 | "Re-rendering page..." | 5-15s |
| L4 | "Re-generating PPT..." | 30-60s |
| L5 | Confirmation dialog "Need to re-collect data (~10-30min)" | 10-30min |

State machine stores: `state="PPT_REVISING", context={"revision_level": "L3"}` (via `ConversationStateMachine.update_context("revision_level", "L3")`). The existing state machine uses `context: Dict[str, Any]` for such metadata — there is no separate `metadata` field.

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
    slide_type: str              # cover/toc/section_title/section-title/content/data/findings/end
    title: str                   # Page title
    data_summary: str            # Data summary (e.g. "6-row table + bar chart")
    chart_type: Optional[str]    # bar/hbar/bar_line/pie/line/radar/scatter/bubble/waterfall/quadrant/None
    key_points: List[str]        # Core content points (2-5 per page)
    data_source: Optional[str]   # Data source marker

@dataclass
class SlideOutline:
    task_id: str
    total_pages: int
    slides: List[SlideOutlineItem]
    confirmed: bool = False
```

### 4.2 Generation Process (P3/P4/P10 fix: from slide_data, not HTML)

Outline is a **projection** of slide_data_list, not a separate extraction step:

```python
class SlideOutlineBuilder:
    """Builds SlideOutline from slide_data_list (truth source)"""
    
    def build(self, slide_data_list: List[Dict]) -> SlideOutline:
        items = []
        for i, sd in enumerate(slide_data_list):
            items.append(SlideOutlineItem(
                page=i + 1,
                slide_type=sd["slide_type"],
                title=sd.get("title", ""),
                data_summary=self._summarize_data(sd),
                chart_type=self._detect_chart_type(sd),
                key_points=self._extract_key_points(sd),
                data_source=sd.get("source_text"),
            ))
        return SlideOutline(task_id=..., total_pages=len(items), slides=items)
    
    def _detect_chart_type(self, sd: Dict) -> Optional[str]:
        """Infer chart type from slide_data images list.
        
        Current pipeline does NOT write chart_type into images[] entries.
        - SmartChartGenerator.generate_chart() returns only a file path string,
          and _auto_generate_charts() appends {"src": ..., "alt": ...} without
          chart_type (html_to_ppt.py:496).
        - ImageProvider.enrich_images() appends {"src": ..., "alt": ..., "image_type": ...}
          where image_type is "product"/"technology"/"illustration" (not chart type).
        
        Detection relies on src path patterns (fragile but currently the only option).
        A future improvement should modify _auto_generate_charts() to also store
        the chart_type from ChartSuggestion into the images[] entry.
        
        Known ChartType values (from chart_generator.py ChartType enum):
        BAR, HBAR, BAR_LINE, PIE, LINE, RADAR, SCATTER, BUBBLE, WATERFALL, QUADRANT
        """
        images = sd.get("images", [])
        for img in images:
            if img.get("image_type") == "chart":
                src = img.get("src", "").lower()
                if "pie" in src: return "pie"
                if "hbar" in src: return "hbar"
                if "bar_line" in src: return "bar_line"
                if "bar" in src: return "bar"
                if "line" in src: return "line"
                if "radar" in src: return "radar"
                if "scatter" in src: return "scatter"
                if "bubble" in src: return "bubble"
                if "waterfall" in src: return "waterfall"
                if "quadrant" in src: return "quadrant"
                return "chart"  # generic chart marker
            # Chart images from SmartChartGenerator don't have image_type at all.
            # They are identified by src path containing chart keywords.
            # Mapping to ChartType enum values: BAR, HBAR, BAR_LINE, PIE, LINE, 
            # RADAR, SCATTER, BUBBLE, WATERFALL, QUADRANT
            src = img.get("src", "")
            alt = img.get("alt", "")
            src_lower = src.lower()
            if any(kw in src_lower for kw in ("chart", "pie", "bar", "line", "radar", "scatter", "bubble", "waterfall", "quadrant", "hbar")):
                if "pie" in src_lower: return "pie"
                if "hbar" in src_lower: return "hbar"
                if "bar_line" in src_lower: return "bar_line"
                if "bar" in src_lower: return "bar"
                if "line" in src_lower: return "line"
                if "radar" in src_lower: return "radar"
                if "scatter" in src_lower: return "scatter"
                if "bubble" in src_lower: return "bubble"
                if "waterfall" in src_lower: return "waterfall"
                if "quadrant" in src_lower: return "quadrant"
                return "chart"
        return None
    
    def _extract_key_points(self, sd: Dict) -> List[str]:
        """Extract 2-5 key points from slide_data items or content."""
        items = sd.get("items", [])
        if items:
            return items[:5]
        content = sd.get("content", "")
        if content:
            sentences = [s.strip() for s in content.split("。") if s.strip()]
            return sentences[:5]
        return []
    
    def _summarize_data(self, sd: Dict) -> str:
        """Summarize data content for outline display."""
        parts = []
        table = sd.get("table_data", [])
        if table:
            parts.append(f"{len(table)-1}-row table")
        images = sd.get("images", [])
        chart_count = sum(1 for img in images if img.get("image_type") == "chart")
        if chart_count:
            parts.append(f"{chart_count} chart{'s' if chart_count > 1 else ''}")
        items = sd.get("items", [])
        if items:
            parts.append(f"{len(items)} bullet points")
        return " + ".join(parts) if parts else "text only"
```

Data flow:
```
ContentSection → SlideDataBuilder → slide_data_list
                                          │
                                          ├──► SlideOutlineBuilder → SlideOutline → user confirmation
                                          │
                                          └──► SlideDataStore.persist(slide_data_list)
```

### 4.3 Outline Modification → slide_data Update (P10 fix)

When user modifies Outline (reorder, delete, edit title/points), changes are applied **directly to slide_data_list**:

| User Action | slide_data_list Update |
|---|---|
| Reorder pages | Reorder slide_data_list entries |
| Delete page | Remove slide_data_list entry |
| Edit title | Update `slide_data["title"]` |
| Edit key points | Update `slide_data["items"]` |
| Change chart type | Update `slide_data["images"]` (replace chart entry with new chart_type) + regenerate chart image via SmartChartGenerator. **Data source**: call `SmartChartGenerator.analyze_content(section_title, content)` with the slide's title and content — this returns a `List[ChartSuggestion]` from which we select the one matching the requested chart_type. If no matching suggestion, construct a `ChartSuggestion` manually from `slide_data["table_data"]` or `slide_data["items"]`. |
| Add page | Insert new slide_data entry (from template) |

After modification, `SlideDataStore.persist()` saves updated slide_data_list. PPT generation reads from store.

### 4.4 Frontend Card Interface

Each page rendered as a card showing:
- Page number, type icon, title, data summary, chart type indicator
- Actions: drag reorder, edit title/points, delete page, add page, change chart type
- User clicks "Confirm" → triggers PPT generation

### 4.5 API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/ppt/{task_id}/outline` | GET | Retrieve Slide Outline (from slide_data_list) |
| `/api/v1/ppt/{task_id}/outline` | PUT | Bulk modify Outline → update slide_data_list → persist (sends full outline) |
| `/api/v1/ppt/{task_id}/outline/slides/{slide_index}` | PATCH | Fine-grained single-slide edit (reorder/delete/edit title/edit points/change chart type). Request body contains `{op: "reorder"|"delete"|"edit_title"|"edit_points"|"change_chart_type", ...}`. Reduces conflict risk vs full-outline PUT. |
| `/api/v1/ppt/{task_id}/generate` | POST | Trigger PPT generation from slide_data_list |

## 5. PPT Revision Levels

### 5.1 Five-Level Strategy

Based on SlideData-First architecture, revisions at deeper levels retreat further in the pipeline:

| Level | Scope | Mechanism | Time | Examples |
|---|---|---|---|---|
| **L0 Review** | No modification | Return analysis result to user | <1s | "Check if this data is accurate", "Review this page" |
| **L1 Atomic** | Single shape text | Direct pptx edit + slide_data update | <1s | Change number, fix typo, change title |
| **L2 Element** | Chart/image | Regenerate element + update slide_data + replace shape | 2-5s | Swap chart type, replace image |
| **L3 Page** | Whole slide | Modify slide_data → re-render single slide → replace in pptx | 5-15s | Adjust layout, restyle, change KPI data |
| **L4 Structure** | Multiple slides | Modify slide_data_list → full re-render PPT | 30-60s | Add/delete pages, reorder, merge/split |
| **L5 Framework** | Entire report | Rollback state machine → re-collect data | 10-30min | Redo chapters, change research direction |

### 5.2 L0: Review — No Modification

When `RevisionOpType.REVIEW` is detected (e.g. "检查数据准确性", "review this page"), the router returns level L0. No pptx or slide_data modification occurs. The analysis result (including identified issues, suggestions, and confidence) is returned to the frontend for display in the revision dialog. This allows users to get feedback without risking unintended changes.

### 5.3 L1: Atomic — Direct pptx + slide_data Update

| Operation | pptx action | slide_data update |
|---|---|---|
| Change text | Modify shape.text_frame | Update corresponding field in slide_data dict |
| Change number | Same | Same |
| Fix punctuation/case | Same | Same |
| Change title | Same | Update `slide_data["title"]` |

Implementation: `PptAtomicEditor` locates shape by `slide_index + shape_name` (both from `PptRevisionRequest`), modifies text directly. Then updates the corresponding field in slide_data via `target_field` path (e.g. `"title"`, `"items[0]"`, `"kpi_data[0].number"`). **No HTML sync needed** — slide_data is the truth source.

**`target_field` path syntax specification (P21 fix)**: Dot-notation with bracket-index for array access. Examples:
- `"title"` → `slide_data["title"]`
- `"items[0]"` → `slide_data["items"][0]`
- `"kpi_data[0].number"` → `slide_data["kpi_data"][0]["number"]`
- `"content"` → `slide_data["content"]`

Parsing is handled by `SlideDataPathResolver` utility class:
```python
class SlideDataPathResolver:
    """Resolves dot-notation + bracket-index paths into slide_data dict locations."""
    _TOKEN_RE = re.compile(r'([^.[]+)|\[(\d+)\]')
    
    @classmethod
    def get(cls, slide_data: Dict, path: str, default=None):
        """Get value at path from slide_data."""
        current = slide_data
        for key_part, index_part in cls._TOKEN_RE.findall(path):
            if index_part:
                if not isinstance(current, list) or int(index_part) >= len(current):
                    return default
                current = current[int(index_part)]
            else:
                if not isinstance(current, dict) or key_part not in current:
                    return default
                current = current[key_part]
        return current
    
    @classmethod
    def set(cls, slide_data: Dict, path: str, value) -> bool:
        """Set value at path in slide_data. Returns False if path is invalid."""
        tokens = cls._TOKEN_RE.findall(path)
        if not tokens:
            return False
        current = slide_data
        for key_part, index_part in tokens[:-1]:
            if index_part:
                if not isinstance(current, list) or int(index_part) >= len(current):
                    return False
                current = current[int(index_part)]
            else:
                if not isinstance(current, dict) or key_part not in current:
                    return False
                current = current[key_part]
        last_key, last_index = tokens[-1]
        if last_index:
            if not isinstance(current, list) or int(last_index) >= len(current):
                return False
            current[int(last_index)] = value
        else:
            if not isinstance(current, dict):
                return False
            current[last_key] = value
        return True
```

### 5.3 L2: Element — Regenerate + Replace

| Operation | Mechanism |
|---|---|
| Swap chart type | SmartChartGenerator creates new chart → replace image shape → update slide_data["images"] entry |
| Replace image | ImageProvider fetches new image → replace image shape → update slide_data["images"] entry. **Note**: `ImageProvider.enrich_images()` only adds images when none exist (line 36: `if images: return`). L2 replacement requires a new `ImageProvider.replace_image(slide_data, image_index, keyword, image_type)` method that fetches a new image for a specific slot regardless of existing images. |

**Note on table data**: Table modification is NOT L2. In python-pptx, tables are special shapes where changing row/column count requires shape reconstruction. Even cell-level data changes may need LayoutEngine re-computation (font sizes, row heights). Therefore, `MODIFY_TABLE` is mapped to L3 by default (see §6.3 DEFAULT_LEVEL_MAP).

Implementation: `PptElementEditor` calls SmartChartGenerator/ImageProvider, replaces shape in pptx, updates slide_data. **No HTML sync needed.**

### 5.4 L3: Page — slide_data → Re-render Single Slide (P2 fix)

| Operation | Mechanism |
|---|---|
| Adjust layout/style | Modify slide_data → LayoutEngine re-computes → SlideRenderer re-renders → replace pptx slide |
| Change content layout | Modify slide_data structure → same pipeline |
| Change KPI values | Modify slide_data items → same pipeline |

**Implementation path for single-slide re-render** (P2 fix):

```python
class PptPageEditor:
    def __init__(self):
        self.selector = TemplateSelector()
        self.registry = TemplateRegistry()
        self.layout_engine = LayoutEngine()
        self.renderer = SlideRenderer(HTMLToPPTConverter.DESIGN)
    
    def edit(self, slide_index: int, slide_data: Dict, pptx: Presentation,
             slide_data_list: List[Dict] = None, styles: Dict = None) -> Slide:
        # 0. Compute section_index from slide_data_list position
        #    section_index = number of section_title slides before this slide
        section_index = self._compute_section_index(slide_data_list or [], slide_index)
        
        # 1. Select template + enhance slide_data (mutates slide_data in-place)
        #    select_and_enhance() returns template_name (str), also adds
        #    kpi_data/comparison_data/section_number/insight_text to slide_data
        template_name = self.selector.select_and_enhance(slide_data, section_index=section_index)
        try:
            template = self.registry.get(template_name)
        except KeyError:
            template = self.registry.get("content_text_only")
        
        # 2. Compute layout overrides
        #    LayoutEngine.compute() is an instance method, returns Dict[str, Dict]
        #    mapping slot_id → position overrides (x, y, width, height, _style_delta)
        layout_overrides = self.layout_engine.compute(slide_data, template)
        
        # 3. Create new slide in a temporary Presentation
        #    python-pptx cannot replace slides in-place, so we render into
        #    a temp Presentation then swap the slide XML.
        temp_prs = Presentation()
        temp_prs.slide_width = pptx.slide_width
        temp_prs.slide_height = pptx.slide_height
        temp_slide = temp_prs.slides.add_slide(temp_prs.slide_layouts[6])  # blank
        
        # 4. Render slide
        #    SlideRenderer.render() signature:
        #      render(self, slide, slide_data, template, styles, page_num, layout_overrides)
        #    styles comes from HTMLToPPTConverter._merge_styles() or DEFAULT_STYLES
        if styles is None:
            styles = HTMLToPPTConverter.DEFAULT_STYLES
        self.renderer.render(temp_slide, slide_data, template, styles,
                           page_num=slide_index + 1, layout_overrides=layout_overrides)
        
        # 5. Replace slide in original pptx
        #    python-pptx has no "replace slide" API. Implementation via
        #    _replace_slide() helper (see below).
        self._replace_slide(pptx, slide_index, temp_slide)
        return pptx.slides[slide_index]
    
    @staticmethod
    def _compute_section_index(slide_data_list: List[Dict], slide_index: int) -> int:
        """Count section_title slides before slide_index to determine section_index.
        
        section_index is needed by TemplateSelector.select_and_enhance() to set
        section_number and section_summary on section_title slides.
        """
        count = 0
        for i in range(min(slide_index, len(slide_data_list))):
            if slide_data_list[i].get("slide_type") in ("section_title", "section-title"):
                count += 1
        return count
    
    def _replace_slide(self, pptx: Presentation, slide_index: int,
                       new_slide: Slide) -> None:
        """Replace slide at slide_index with new_slide via XML manipulation.
        
        python-pptx has no replace-slide API. Two approaches are possible:
        
        Approach A — Full re-render (L4 degradation, INITIAL IMPLEMENTATION):
          Simply re-render all slides from slide_data_list using the existing
          HTMLToPPTConverter._create_pptx_document() pipeline. This is always
          correct but costs 30-60s regardless of how many slides changed.
        
        Approach B — XML swap (future optimization, requires feature flag):
          1. Serialize new_slide from temp_prs to XML bytes
          2. In target pptx, get the slide part at slide_index:
             slide_part = pptx.slides[slide_index].part
          3. Replace the slide's XML content:
             slide_part._element = copy.deepcopy(new_slide._element)
          4. Copy image/chart relationships from temp_prs into pptx's package:
             - For each rel in new_slide.part.rels.values():
               - If rel.is_external: add external rel to slide_part
               - Else: copy the rel target blob into pptx's package and add rel
          5. Update the sldIdLst if needed:
             sldIdLst = pptx.element.sldIdLst  (CT_Presentation.sldIdLst)
             This is accessible via pptx.element (not pptx.presentation).
          6. This requires accessing python-pptx internals (_element, part, rels)
             which are not part of the public API and may break on version upgrades.
        
        IMPORTANT: python-pptx internal API notes:
        - pptx.presentation does NOT exist. Use pptx.element (CT_Presentation) instead.
        - pptx.element.sldIdLst IS accessible (CT_Presentation internal property).
        - pptx.part.drop_rel() DOES exist on PresentationPart.
        - Safe internal access: slide._element, slide.part, part.rels
        """
        if not os.environ.get("PPT_ENABLE_L3_SINGLE_SLIDE"):
            raise NotImplementedError(
                "L3 single-slide replacement not enabled. "
                "Fallback: use L4 full re-render instead."
            )
        # Approach B implementation — to be completed with feature flag
        raise NotImplementedError("L3 XML swap not yet implemented")
```

**Implementation note on _replace_slide**: This is the hardest technical challenge in L3. python-pptx does not support replacing a slide in-place. The XML swap approach requires:
1. Deep-copying the new slide's XML element (`<p:sld>`) and all its relationships (images, charts, embedded objects)
2. Inserting it at the correct position in the `<p:sldIdLst>` 
3. Removing the old slide's part and relationships

**L3 degradation strategy (P20 fix)**: In the initial implementation, L3 **always degrades to L4** (full re-render all slides). This means:
- `PptPageEditor.edit()` internally calls `PptStructureEditor.edit()` with the full slide_data_list
- The L3/L4 distinction is purely a **performance optimization** to be enabled later
- L3 performance target (<15s) is not met initially; L4 cost (~30-60s) is accepted for correctness
- `_replace_slide()` XML manipulation is implemented and validated in a separate branch before being enabled in production
- A feature flag `PPT_ENABLE_L3_SINGLE_SLIDE` (default `false`) controls whether true L3 is attempted

When the feature flag is enabled, the fallback chain is:
1. Attempt `_replace_slide()` XML swap
2. If XML swap fails (raises any exception), catch and degrade to L4 full re-render
3. Log the degradation for monitoring

This approach is consistent with P13: "same pipeline, L3=1 slide, L4=all slides" — the pipeline code is identical, only the scope differs.

**Key advantage**: LayoutEngine dynamically adjusts typography based on new content/height. No hardcoded dimensions.

### 5.5 L4: Structure — slide_data_list → Full Re-render

| Operation | Mechanism |
|---|---|
| Add/delete pages | Modify slide_data_list (add/remove entries) → full slide_data→PPT pipeline |
| Reorder pages | Reorder slide_data_list entries → same |
| Merge/split pages | Modify slide_data_list structure → same |

Implementation: `PptStructureEditor` modifies slide_data_list, runs complete rendering pipeline. Simpler than v1.0 because no HTML modification needed.

### 5.6 L5: Framework — Pipeline Rollback (P7 fix: 3 rollback depths)

L5 is not a single rollback target — it has 3 depths depending on how fundamental the change is:

| Depth | Target State | When | Example |
|---|---|---|---|
| L5a | `SLIDE_OUTLINE_CONFIRM` | Keep data, only restructure pages | "Reorganize into 3 chapters instead of 5" |
| L5b | `EXECUTING` | Keep framework, re-collect data | "Add competitor analysis data" |
| L5c | `FRAMEWORK_CONFIRM` | Full redo | "Change entire research direction" |

Routing logic (executable via AnalysisResult fields):

```python
def _determine_l5_depth(self, analysis: AnalysisResult, ppt_context: Dict) -> str:
    """Determine L5 rollback depth based on analysis result.
    
    Decision criteria use RevisionAction fields from AnalysisResult:
    - action_type: ADD/DELETE/REORDER/SPLIT/MERGE → structural → L5a
    - action_type: MODIFY + parameters indicating new data → L5b
    - is_global_feedback=True + ambiguous target → L5c
    """
    if not analysis.intents:
        return "L5c"  # no clear intent → full redo
    
    action = analysis.intents[0]
    structural_ops = {
        RevisionOpType.ADD, RevisionOpType.DELETE, 
        RevisionOpType.REORDER, RevisionOpType.SPLIT,
        RevisionOpType.MERGE, RevisionOpType.SWAP,
    }
    
    if action.action_type in structural_ops:
        return "L5a"  # page structure only → SLIDE_OUTLINE_CONFIRM
    
    if action.action_type == RevisionOpType.MODIFY:
        params = action.parameters
        # If user explicitly requests new data/collection
        if params.get("requires_new_data", False):
            return "L5b"  # new data needed → EXECUTING
        # If modification scope is global (no specific target or whole report)
        if analysis.is_global_feedback:
            return "L5c"  # fundamental change → FRAMEWORK_CONFIRM
        return "L5a"  # structural reorganization without new data
    
    return "L5c"  # default: full redo for safety
```

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
├── ppt_revision_types.py        # PPT-specific revision types
└── slide_data_path_resolver.py  # target_field path resolution utility

src/converters/
├── slide_data_builder.py        # NEW: ContentSection → slide_data (bypasses HTML round-trip; SlideElementParser retained for HTML preview path)
├── slide_data_store.py          # NEW: slide_data persistence (truth source)
└── slide_outline_builder.py     # NEW: slide_data_list → SlideOutline projection
```

### 6.2 PptRevisionService — Entry Point

```python
class PptRevisionService:
    def __init__(self, slide_data_store: SlideDataStore, 
                 chart_generator, image_provider):
        self.store = slide_data_store
        self.pptx_path = slide_data_store.pptx_path  # P22 fix: path managed by store, auto-updates on rollback
        self.router = PptRevisionRouter()
        self.locator = PptSlideLocator()
        self.atomic = PptAtomicEditor()
        self.element = PptElementEditor(chart_generator, image_provider)
        self.page = PptPageEditor()
        self.structure = PptStructureEditor()
        self.version_mgr = PptVersionManager()
    
    async def revise(self, request: PptRevisionRequest) -> PptRevisionResult:
        # 0. Refresh pptx_path from store (may have changed after rollback)
        self.pptx_path = self.store.pptx_path
        
        # 1. Snapshot current version
        self.version_mgr.snapshot(self.pptx_path)
        # 2. Route to revision level (if not already determined by click-select)
        if request.source == "click":
            # Click-select: level is determined by frontend, but validate consistency
            level = request.revision_level or "L1"
            level = self._validate_click_level(level, request)  # P23 fix
        else:
            # Natural language: full routing pipeline
            routed = await self.router.route(
                request.description, 
                self.store.load(), 
                {"task_id": request.task_id}
            )
            request.revision_level = routed.revision_level
            request.intent_analysis = routed.intent_analysis
            level = routed.revision_level
        # 3. Execute revision
        result = await self._dispatch(level, request)
        # 4. Persist updated slide_data
        self.store.persist()
        return result
    
    def _validate_click_level(self, level: str, request: PptRevisionRequest) -> str:
        """Validate that click-selected level is consistent with revision_type.
        
        Prevents frontend misclassification (e.g. MODIFY_TABLE sent as L1).
        Uses RevisionOpType enum for consistency with DEFAULT_LEVEL_MAP.
        """
        try:
            op_type = RevisionOpType(request.revision_type)
        except ValueError:
            return level  # unknown type, accept as-is
        
        INCONSISTENT_MAP = {
            RevisionOpType.MODIFY_TABLE: {"L1"},      # must be at least L3
            RevisionOpType.MODIFY_CHART: {"L1"},      # must be at least L2
            RevisionOpType.ADD: {"L1", "L2", "L3"},  # must be L4
            RevisionOpType.DELETE: {"L1", "L2", "L3"},  # must be L4
        }
        blocked = INCONSISTENT_MAP.get(op_type, set())
        if level in blocked:
            corrected = {"L1": "L3", "L2": "L3", "L3": "L4"}.get(level, "L4")
            logger.warning(
                f"Click level {level} inconsistent with revision_type "
                f"{request.revision_type}, correcting to {corrected}"
            )
            return corrected
        return level
    
    async def _dispatch(self, level, request):
        if level == "L0":
            return PptRevisionResult(success=True, level="L0", 
                                     message="Review only — no modification applied",
                                     intent_analysis=request.intent_analysis)
        elif level == "L1":
            return await self.atomic.edit(request, self.store, self.pptx_path)
        elif level == "L2":
            return await self.element.edit(request, self.store, self.pptx_path)
        elif level == "L3":
            return await self.page.edit(request, self.store, self.pptx_path)
        elif level == "L4":
            return await self.structure.edit(request, self.store, self.pptx_path)
        elif level.startswith("L5"):
            return await self._rollback_framework(request)
```

### 6.3 PptRevisionRouter — Intelligent Routing (P5/P8 fix)

**Reuses existing `RevisionIntentAnalyzer` (LLM-first + regex fallback). No hardcoded keywords.**

**P5 fix**: `RevisionIntentAnalyzer.analyze()` expects a `Report` object with `sections`. We provide a `PptReportAdapter` that wraps slide_data_list as a Report:

```python
class PptReportAdapter:
    """Adapts slide_data_list to Report interface for RevisionIntentAnalyzer.
    
    RevisionIntentAnalyzer._build_section_context() only reads:
      - report.sections (list)
      - sec.title (via getattr)
      - sec.id (via getattr, fallback)
    
    The 'content' and 'type' fields are NOT used by the current
    RevisionIntentAnalyzer, but are included here for:
    1. Future LLM prompt extensions that may include section content
    2. Consistency with the Report interface contract
    """
    
    def __init__(self, slide_data_list: List[Dict], task_id: str):
        self.id = task_id
        self.sections = [
            ReportSection(
                id=f"slide_{i}",
                title=sd.get("title", f"Slide {i+1}"),
                content=self._build_content_text(sd),
                type=self._map_type(sd["slide_type"]),
            )
            for i, sd in enumerate(slide_data_list)
        ]
    
    def _build_content_text(self, sd: Dict) -> str:
        parts = []
        if sd.get("title"): parts.append(sd["title"])
        if sd.get("content"): parts.append(sd["content"])
        if sd.get("items"): parts.extend(sd["items"])
        if sd.get("table_data"):
            for row in sd.get("table_data", [])[:3]:  # first 3 rows including header
                parts.append(" | ".join(str(c) for c in row))
        return "\n".join(parts)
    
    def _map_type(self, slide_type: str) -> str:
        """Map slide_type to section type for RevisionIntentAnalyzer context."""
        mapping = {
            "cover": "cover",
            "toc": "toc",
            "section_title": "section_title",
            "section-title": "section_title",
            "content": "content",
            "data": "data",
            "findings": "findings",
            "end": "end",
        }
        return mapping.get(slide_type, "content")
```

**P8 fix**: LEVEL_MAP is a **default** mapping, but the router can **dynamically upgrade** the level based on impact analysis:

```python
class PptRevisionRouter:
    DEFAULT_LEVEL_MAP = {
        # L1: Atomic text changes (direct pptx shape edit + slide_data update)
        RevisionOpType.REPLACE_TEXT: "L1",
        RevisionOpType.FIX_PUNCTUATION: "L1",
        RevisionOpType.CHANGE_CASE: "L1",
        RevisionOpType.UPDATE_TITLE: "L1",
        # L2: Element swap (chart/image replacement, no layout re-computation)
        RevisionOpType.MODIFY_CHART: "L2",
        RevisionOpType.ADD_ELEMENT: "L2",
        RevisionOpType.DELETE_ELEMENT: "L2",
        # L3: Page re-render (LayoutEngine re-computation required)
        # MODIFY_TABLE is L3 because python-pptx tables are special shapes —
        # changing data requires shape reconstruction + layout re-computation.
        RevisionOpType.MODIFY_TABLE: "L3",
        RevisionOpType.MODIFY: "L3",
        RevisionOpType.STYLE: "L3",
        # L4: Structural changes (multiple slides affected)
        RevisionOpType.ADD: "L4",
        RevisionOpType.DELETE: "L4",
        RevisionOpType.MERGE: "L4",
        RevisionOpType.SPLIT: "L4",
        RevisionOpType.SWAP: "L4",
        RevisionOpType.REORDER: "L4",
        RevisionOpType.DEDUP: "L4",
        RevisionOpType.COPY: "L4",
        RevisionOpType.TRANSLATE: "L4",
        # REVIEW is not an actionable revision — return analysis result without re-render
        RevisionOpType.REVIEW: "L0",    # P24 fix: L0 = no-op, return analysis to user
        RevisionOpType.UNKNOWN: "L3",   # safe default for uncertain operations
    }
    
    def __init__(self):
        self.intent_analyzer = RevisionIntentAnalyzer()
    
    async def route(self, user_message: str, slide_data_list: List[Dict], 
                    ppt_context: Dict) -> PptRevisionRequest:
        # 1. Adapt slide_data to Report interface (P5 fix)
        report = PptReportAdapter(slide_data_list, ppt_context["task_id"])
        
        # 2. Call existing RevisionIntentAnalyzer (LLM-first + regex fallback)
        analysis = await self.intent_analyzer.analyze(user_message, report)
        
        # 3. Get default level from map
        if analysis.intents:
            action_type = analysis.intents[0].action_type
            level = self.DEFAULT_LEVEL_MAP.get(action_type, "L3")
        else:
            level = "L3"
        
        # 4. Dynamic level upgrade based on impact (P8 fix)
        level = self._upgrade_if_needed(level, analysis, ppt_context)
        
        # 5. Extract PPT location from analysis
        slide_index = self._extract_slide_index(analysis, ppt_context)
        slide_title = self._extract_slide_title(analysis, ppt_context)
        
        # 6. Assemble request
        return PptRevisionRequest(
            task_id=ppt_context["task_id"],
            source="natural_language",
            slide_index=slide_index,
            slide_title=slide_title,
            description=user_message,
            intent_analysis=analysis,
            revision_level=level,
        )
    
    def _upgrade_if_needed(self, level: str, analysis, ppt_context: Dict) -> str:
        """Upgrade level if operation impact exceeds default level scope.
        
        Upgrade rules:
        - L2 → L3: if chart swap affects surrounding layout (e.g. chart size
          changes significantly, requiring LayoutEngine re-computation)
        - L3 → L4: if page edit triggers cross-slide effects (e.g. section
          renumbering, TOC update)
        - L4 → L5: if structural change requires new data collection
        """
        if level == "L2" and analysis.intents:
            op = analysis.intents[0].action_type
            if op == RevisionOpType.MODIFY_CHART:
                # Chart type change that significantly alters layout → upgrade to L3
                if ppt_context.get("chart_size_changes", False):
                    level = "L3"
        if level == "L3" and analysis.intents:
            # Page-level edit that affects other slides (e.g. section title change → TOC update)
            if ppt_context.get("affects_other_slides", False):
                level = "L4"
        return level
    
    def _extract_slide_index(self, analysis: AnalysisResult, ppt_context: Dict) -> Optional[int]:
        """Extract slide index from analysis result.
        
        Priority:
        1. section_refs with ref_type="index" → use index value directly
        2. target.raw_text containing page number patterns ("第5页", "slide 5") → parse
        3. ppt_context.get("current_slide_index") → frontend-provided context
        4. None → PptSlideLocator will resolve by title/keyword later
        """
        if not analysis.intents:
            return ppt_context.get("current_slide_index")
        
        target = analysis.intents[0].target
        
        for ref in target.section_refs:
            if ref.ref_type == RefType.INDEX and ref.index is not None:
                return ref.index
        
        import re
        page_match = re.search(r'第(\d+)页|slide\s+(\d+)', target.raw_text, re.I)
        if page_match:
            num = int(page_match.group(1) or page_match.group(2))
            return max(0, num - 1)  # 1-based → 0-based
        
        return ppt_context.get("current_slide_index")
    
    def _extract_slide_title(self, analysis: AnalysisResult, ppt_context: Dict) -> Optional[str]:
        """Extract slide title from analysis result.
        
        Uses target.raw_text as the title keyword for PptSlideLocator
        title-match strategy when slide_index is not available.
        """
        if not analysis.intents:
            return None
        return analysis.intents[0].target.raw_text or None
```

### 6.4 YAML Extension (P11 clarification)

New section in `config/keyword_mappings.yaml` for PPT-specific regex fallback patterns.

**Important**: These patterns are **regex fallback only** — LLM analysis is always tried first via `RevisionIntentAnalyzer`. YAML patterns only activate when LLM is unavailable or returns low confidence. This is consistent with the existing `KeywordRegistry` architecture and does NOT violate the "no hardcoded keywords" principle.

**KeywordRegistry modification required (P25 fix: merged fallback map)**: The existing `KeywordRegistry._parse_revision_intents()` only parses the top-level `revision_intents` key. A new `_parse_ppt_revision_intents()` method must be added to parse the `ppt_revision_intents` section. **However, PPT patterns are merged into the same `INTENT_TO_REVISION_MAP_V2` used by `RevisionIntentAnalyzer._fallback_to_regex()`**, not maintained as a separate lookup. This ensures a single fallback path — `PptRevisionRouter` does NOT need a separate `_fallback_to_ppt_regex()` method.

Implementation: `_init_patterns_from_registry()` in `revision_intent_analyzer.py` calls both `registry.get_revision_pattern_strings()` (existing) and `registry.get_ppt_revision_pattern_strings()` (new). Both are merged into `INTENT_TO_REVISION_MAP_V2`. The `ppt_level` field in YAML is used only by `PptRevisionRouter.DEFAULT_LEVEL_MAP` to override the default level for PPT-specific patterns — it is NOT used by the regex fallback itself.

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
- Available PPT revision levels: L1 (atomic text change), L2 (chart/image swap), 
  L3 (page re-layout), L4 (add/delete/merge/split pages), L5 (framework rollback)
- When user refers to "第5页" or "slide 5", set target.section_refs[0].ref_type = "index", target.section_refs[0].index = 4
- When user says "换饼图", map to modify_chart with parameters.chart_type = "pie"
- When user says "这页太挤了", map to modify with ppt_level = "L3"
- When user requests require new data collection (e.g. "add competitor data", "research new market", "补充竞品数据"), set parameters.requires_new_data = true
- When user says the whole report needs rework (e.g. "重做", "完全不行"), set is_global_feedback = true
```

### 6.6 PptSlideLocator — Three Location Strategies

| Strategy | Input | Mechanism |
|---|---|---|
| Page number | `"第5页"` / `slide_index=4` | Direct index access |
| Title match | `"市场规模"` | Find slide whose title shape text contains keyword |
| Content keyword | `"KPI"` | Find slide whose text content contains keyword (semantic match via `SectionLocatorV2`) |

### 6.7 PptVersionManager — Complete Version Snapshots (P14 fix)

- Before each revision: copy current pptx to `data/revisions/{task_id}/v{N}.pptx`
- Keep last 10 versions per task, delete oldest when exceeded
- Support rollback: `rollback(version=N)` → copy snapshot back to active path
- Store version metadata: `{version, timestamp, revision_level, user_message}`

**Storage cleanup strategy** (P14):
- Max 10 versions per task (configurable via `PPT_MAX_VERSIONS` env var)
- On task completion (`COMPLETED` state), keep only last 3 versions
- Global cleanup cron: delete `data/revisions/` entries older than 7 days
- Estimated storage: 10 × 500KB × 100 concurrent = 500MB peak, auto-cleaned to ~150MB after completion

### 6.8 SlideData Sync (replaces HTML Sync from v1.0)

With SlideData-First architecture, **no HTML sync is needed**:

- L1/L2: Edit pptx shape + update slide_data dict → `SlideDataStore.persist()`
- L3: Modify slide_data → re-render slide → replace in pptx → `SlideDataStore.persist()`
- L4: Modify slide_data_list → full re-render → `SlideDataStore.persist()`
- HTML is generated on-demand for preview only, never needs to be "synced"

If slide_data and pptx somehow diverge (e.g. external pptx edit):
- **Version hash definition**: SHA-256 of `slide_data_list` JSON (canonical sorted-keys serialization). Stored in `SlideDataStore` metadata alongside the pptx file path. After any revision, both slide_data JSON hash and pptx file are updated atomically.
- **Divergence detection**: On each revision, compare current `slide_data_list` JSON hash against stored hash. Also compare pptx file mtime against stored mtime. If either mismatches without a corresponding revision record, divergence is detected.
- **Recovery strategy (P26 fix: degraded recovery)**: Re-deriving slide_data from pptx via python-pptx can only recover: shape text, table data, image references, and basic layout positions. It **cannot recover**: `slide_type` (logical classification), `kpi_data` (TemplateSelector detection result), `comparison_data` (TemplateSelector detection result), `insight_text` (TemplateSelector extraction), `source_text` (data source marker), `chart_type` (chart metadata). Therefore:
  1. **Primary recovery**: Attempt to restore from the most recent `SlideDataStore` backup (`data/slide_data/{task_id}.json.bak`) before the divergence
  2. **Fallback recovery**: If no backup exists, re-derive from pptx and mark the result as `"recovery_mode": "degraded"`. Prompt user: "PPT was externally modified. A partial data recovery was performed — some metadata (KPI detection, chart types, data sources) may be lost. Please verify the outline and re-confirm."
  3. **Full recovery**: If user confirms degradation is unacceptable, trigger L5b rollback to `EXECUTING` state to re-collect data and regenerate from ContentSection

## 7. Mixed-Mode Revision Interaction

### 7.1 Click-Select (Simple Operations)

Users interact directly on PPT preview page:

| Action | Trigger | Level | Example |
|---|---|---|---|
| Change text | Click text → edit popup | L1 | Edit title, number |
| Swap chart | Click chart → select type | L2 | Bar → Pie |
| Replace image | Click image → refresh | L2 | New illustration |
| Delete page | Page × button | L4 | Remove page (backend validates: must keep cover + end) |
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
- L0: Instant, show analysis result in dialog (no PPT change)
- L1: Instant, no loading
- L2: 2-5s loading, "Updating chart..."
- L3: 5-15s loading, "Re-rendering page..."
- L4: 30-60s loading, "Re-generating PPT..."
- L5: Confirmation dialog "Need to re-collect data (~10-30min)", proceed after user confirms

## 8. API Endpoints Summary

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/ppt/{task_id}/outline` | GET | Get Slide Outline |
| `/api/v1/ppt/{task_id}/outline` | PUT | Bulk modify and confirm Outline |
| `/api/v1/ppt/{task_id}/outline/slides/{slide_index}` | PATCH | Fine-grained single-slide outline edit |
| `/api/v1/ppt/{task_id}/generate` | POST | Trigger PPT generation |
| `/api/v1/ppt/{task_id}/preview` | GET | Preview PPT |
| `/api/v1/ppt/{task_id}/revise` | POST | Submit revision request |
| `/api/v1/ppt/{task_id}/versions` | GET | Get version history |
| `/api/v1/ppt/{task_id}/rollback` | POST | Rollback to specified version |
| `/api/v1/ppt/{task_id}/export` | POST | Final export |
| `/api/v1/ppt/{task_id}/confirm` | POST | Confirm final version |

### Revision Request Format (P12 fix: added source field)

```python
@dataclass
class PptRevisionRequest:
    task_id: str
    # Interaction source (P12 fix)
    source: str = "natural_language"  # "click" | "natural_language"
    # Location (choose one)
    slide_index: Optional[int] = None
    slide_title: Optional[str] = None
    content_keyword: Optional[str] = None
    # L1 atomic-specific: shape-level location (required for L1 click-select)
    shape_name: Optional[str] = None     # P27 fix: python-pptx shape.name (stable unique identifier, survives add/delete of other shapes)
    shape_index: Optional[int] = None    # shape index within slide (fallback when shape_name unavailable; may shift after shape mutations)
    # Revision content
    revision_type: str = "modify"        # maps to RevisionOpType via DEFAULT_LEVEL_MAP
    description: str = ""
    # L2 element-specific
    new_chart_type: Optional[str] = None
    new_data: Optional[Dict] = None
    # L1 atomic-specific (from click-select)
    target_field: Optional[str] = None   # e.g. "title", "items[0]", "kpi_data[0].number"
    new_value: Optional[str] = None
    # Internal (from RevisionIntentAnalyzer)
    intent_analysis: Optional[AnalysisResult] = None
    revision_level: Optional[str] = None
```

`source` field determines routing behavior:
- `source="click"`: Skip intent analysis, use direct field mapping (slide_index, shape_name, shape_index, target_field, new_value). `revision_level` is set by frontend based on the clicked element type, but validated via `_validate_click_level()`.
- `source="natural_language"`: Full RevisionIntentAnalyzer pipeline via `PptRevisionRouter.route()`

## 9. Error Handling

| Scenario | Handling |
|---|---|
| PPT corrupt after revision | Auto-rollback to previous version snapshot |
| L1 pptx edit succeeds but slide_data update fails | **Atomic operation (P28 fix)**: Both pptx edit and slide_data update must succeed or both roll back. Implementation: (1) apply pptx edit, (2) apply slide_data update, (3) if step 2 fails, revert pptx edit using version snapshot. Never allow slide_data to be marked "dirty" — this violates the SlideData-First principle. |
| L2 chart generation fails | Keep original chart, return failure reason |
| L3 single-slide render fails | Escalate to L4 full re-render (P13: simplified — L4 is same pipeline, just all slides) |
| L4 full re-render fails | Rollback to previous version snapshot |
| L5 data collection fails | No impact on current PPT, return error info |
| Concurrent revision conflict | Optimistic lock: `SlideDataStore` stores a `version` counter incremented on each persist. On revision, compare request's `base_version` with store's current `version`. If mismatch, reject and prompt user to refresh. |
| slide_data/pptx divergence detected | 3-tier recovery per §6.8 (backup restore → degraded re-derive → L5b full re-collection) |

## 10. Edge Cases

| Scenario | Handling |
|---|---|
| User deletes all pages | Reject: must keep cover + end (enforced in `PptStructureEditor` backend validation, not just frontend) |
| User modifies cover page | L3: re-render cover |
| User changes KPI display value but not data | L1: change display only (data change → L5) |
| Revision exceeds 10 rounds | Prompt "建议重新确认框架", guide to L5 |
| Slide Outline data stale after confirmation | Mark outline as stale, prompt re-confirmation |
| PPT externally modified | Version mismatch, reject revision, prompt re-generation |

## 11. Testing Strategy (P15 fix: PPT-specific test scenarios)

| Level | Test Content |
|---|---|
| Unit | PptSlideLocator, PptRevisionRouter routing, PptAtomicEditor text change, PptVersionManager snapshot/rollback, SlideDataBuilder, SlideDataStore, SlideOutlineBuilder, PptReportAdapter, SlideDataPathResolver (path get/set round-trip, invalid path handling) |
| Unit (PPT-specific) | **LayoutEngine re-computation after revision** (verify font_size/row_height/line_spacing recalculate correctly), **KPI re-detection after data change** (verify TemplateSelector re-triggers), **chart-table data consistency** (verify chart image matches table_data after L2 revision), **slide_data↔pptx round-trip** (edit slide_data → render → read back → verify) |
| Integration | L1→verify pptx+slide_data sync, L2→verify new chart+slide_data, L3→verify layout re-render, L4→verify full PPT |
| Integration (PPT-specific) | **L3 MODIFY_TABLE → verify LayoutEngine re-runs** (table data change triggers re-render), **L3 re-render → verify only target slide changes** (other slides untouched), **L4 re-order → verify slide_data_list order matches pptx slide order** |
| E2E | Full flow: framework confirm → data collection → outline confirm → PPT gen → preview → revise (L1-L4) → confirm → export |
| Regression | After revision, ~160 existing LayoutEngine/SlideRenderer/TemplateSelector tests still pass (71 layout_engine + 4 ppt_layout + 30 slide_renderer + 5 build_slide_dict + 11 slide_splitting + 6 template_integration + 9 template_registry + 24 select_and_enhance; count as of v2.2 design, verify at implementation time) |

## 12. Performance Targets

| Operation | Target |
|---|---|
| L0 Review (no-op) | < 1 second |
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

- `RevisionOpType` enum — all 21 existing values are used in `DEFAULT_LEVEL_MAP`. Note: `REVIEW` is mapped to "L0" (no-op, returns analysis to user without re-rendering); `UNKNOWN` is mapped to L3 as a safe default. No new PPT-specific RevisionOpType values are needed.
- `RevisionIntentAnalyzer` for intelligent intent routing (LLM-first + YAML fallback)
- `KeywordRegistry` for PPT-specific regex fallback patterns (requires adding `_parse_ppt_revision_intents()` method)
- `SectionLocatorV2` semantic location logic (adapted for slide location via `PptSlideLocator`)
- `SnapshotManager` **design pattern** (not code reuse) — `PptVersionManager` borrows the snapshot-before-edit pattern, but implements it as file-based pptx copy (not in-memory Report serialization). `SnapshotManager` stores Report JSON in memory; `PptVersionManager` stores pptx binary files on disk. These are fundamentally different storage mechanisms.

## 14. Implementation Priority

| Phase | Scope | Priority |
|---|---|---|
| P0 | SlideDataBuilder (ContentSection → slide_data direct) + SlideDataStore + SlideOutlineBuilder | High |
| P0 | Slide Outline generation + confirmation API | High |
| P1 | PptRevisionService skeleton + PptVersionManager + PptSlideLocator | High |
| P1 | PptRevisionRouter + PptReportAdapter (reuse RevisionIntentAnalyzer) | High |
| P2 | L1 Atomic editor (pptx direct edit + slide_data update) | High |
| P2 | L2 Element editor (chart/image swap + slide_data update) | Medium |
| P3 | L3 Page editor (initially degrades to L4; feature flag `PPT_ENABLE_L3_SINGLE_SLIDE` for true single-slide re-render) | Medium |
| P3 | L4 Structure editor (slide_data_list → full re-render) | Medium |
| P4 | L5 Framework rollback (3-depth: L5a/L5b/L5c) | Low |
| P4 | Frontend card interface for Outline | Medium |
| P4 | Frontend click-select interaction | Medium |

## 15. v1.0 → v2.0 Change Summary

| Issue | v1.0 (HTML-First) | v2.0 (SlideData-First) |
|---|---|---|
| P1: HTML sync infeasible | Dual-write pptx+HTML, unreliable mapping | No HTML sync; slide_data is truth source |
| P2: L3 single-slide re-render | No implementation path | temp Presentation + _replace_slide() helper |
| P3: Outline data source | Extracted from HTML (circular) | Projected from slide_data_list (natural) |
| P4: Truth source | HTML (intermediate format) | slide_data (structured data model) |
| P5: Router interface mismatch | Passed Report directly | PptReportAdapter wraps slide_data as Report |
| P6: State transitions | Undefined | VALID_TRANSITIONS dict with all new states |
| P7: L5 rollback | Single target (FRAMEWORK_CONFIRM) | 3 depths: L5a/L5b/L5c |
| P8: Static LEVEL_MAP | OpType → Level fixed | DEFAULT_LEVEL_MAP + dynamic _upgrade_if_needed() |
| P9: PPT_REVISING undifferentiated | Single state | revision_level metadata attribute |
| P10: Outline→HTML path | Missing | Outline→slide_data_list update→SlideDataStore.persist() |
| P11: YAML clarification | Implicit | Explicit: LLM-first, YAML is regex fallback only |
| P12: Request source | Mixed, no distinction | source field: "click" vs "natural_language" |
| P13: L3/L4 distinction | Over-engineered | Simplified: same pipeline, L3=1 slide, L4=all slides |
| P14: Snapshot storage | No cleanup strategy | Max 10/task, 3 on completion, 7-day global cleanup |
| P15: Test scenarios | Generic | PPT-specific: LayoutEngine re-computation, KPI re-detection, chart-table consistency |
| P16: L3 API calls | Wrong (static methods, missing params) | Correct instance-based API: TemplateSelector().select_and_enhance(), LayoutEngine().compute(), SlideRenderer(design).render() |
| P17: MODIFY_TABLE level | L2 (incorrect) | L3 (python-pptx tables require shape reconstruction + layout re-computation) |
| P18: PptRevisionRequest | Missing shape_index | Added shape_index for L1 atomic shape-level location |
| P19: VALID_TRANSITIONS | Only new states listed, existing transitions omitted | Full VALID_TRANSITIONS dict preserving all existing transitions + adding new states |

## 16. v2.1 → v2.2 Change Summary (22 issues fixed)

| Issue | v2.1 | v2.2 |
|---|---|---|
| P20: L3 `_replace_slide` no degradation strategy | `NotImplementedError` with vague "can fall back" note | L3 always degrades to L4 initially; feature flag `PPT_ENABLE_L3_SINGLE_SLIDE` controls true L3; explicit fallback chain |
| P21: `target_field` path syntax undefined | No specification, no parser | `SlideDataPathResolver` utility class with dot-notation + bracket-index; `get()`/`set()` methods; invalid path returns default/false |
| P22: `pptx_path` not updated on rollback | `PptRevisionService.__init__(pptx_path: str)` — static path | Path managed by `SlideDataStore.pptx_path`; refreshed at start of each `revise()` call |
| P23: Click path skips level validation | `level = request.revision_level or "L1"` — no checks | `_validate_click_level()` cross-checks revision_type vs level; auto-corrects inconsistencies (e.g. MODIFY_TABLE+L1 → L3) |
| P24: REVIEW mapped to L3 | `REVIEW → L3` causes unnecessary re-render | `REVIEW → L0` (no-op); returns analysis to user without modifying PPT |
| P25: PPT regex fallback separate path | `PptRevisionRouter._fallback_to_ppt_regex()` — parallel system | PPT patterns merged into `INTENT_TO_REVISION_MAP_V2`; single fallback path in `RevisionIntentAnalyzer` |
| P26: pptx→slide_data re-derive loses metadata | "Re-derive from pptx, mark recovered" — no acknowledgment of data loss | 3-tier recovery: (1) backup restore, (2) degraded re-derive with `"recovery_mode": "degraded"` + user warning, (3) L5b full re-collection |
| P27: `shape_index` unstable | `shape_index` only — may shift after shape mutations | `shape_name` (primary, stable) + `shape_index` (fallback) dual identification |
| P28: L1 slide_data fail violates SlideData-First | "Keep pptx change, mark slide_data dirty" | Atomic operation: both pptx+slide_data succeed or both roll back via version snapshot |
| P29: `_detect_chart_type` fragile path inference | Only `images[].src` path pattern matching | Priority: `images[].chart_type` field (set by SmartChartGenerator) → fallback to src path |
| P30: Change chart type missing data source | "regenerate chart image via SmartChartGenerator" — no data source | Explicit: extract data from `table_data`/`items` to construct `ChartSuggestion` |
| P31: Outline API too coarse-grained | Single PUT endpoint for full outline | Added PATCH `/outline/slides/{slide_index}` for fine-grained single-slide edits |
| P32: `FRAMEWORK_CONFIRM → PREVIEWING` unclear | No comment on why this transition exists | Added comment: "legacy: preview existing report before data collection" |
| P33: `metadata` field doesn't exist in state machine | `state="PPT_REVISING", metadata={"revision_level": "L3"}` | Changed to `context={"revision_level": "L3"}` via `update_context()` |
| P34: PPT_REVISING→SLIDE_OUTLINE_CONFIRM outline source | Not specified | Explicit: "Outline is always projected from CURRENT slide_data_list (reflecting any L1/L2/L3 modifications already applied)" |
| P35: `section_index` parameter source unclear | `section_index: int = 0` — hardcoded default | `_compute_section_index()` method counts section_title slides before target slide |
| P36: `requires_new_data` not in LLM prompt | L5 routing uses `parameters.requires_new_data` but prompt doesn't guide LLM to set it | Added to §6.5 prompt extension: "set parameters.requires_new_data = true" |
| P37: `_extract_slide_index/title` missing implementation | Method signatures only | Full implementation: section_refs index extraction → page number regex → context fallback |
| P38: `_upgrade_if_needed` code block not closed | Missing closing `}` for class | Closed with `_extract_slide_index`/`_extract_slide_title` methods |
| P39: Delete page lacks backend validation | "Reject: must keep cover + end" — frontend only | Added: "enforced in `PptStructureEditor` backend validation" |
| P40: L0 Review level missing | No level for review-only operations | Added L0 (no-op, returns analysis to user); updated §5.1, §3.1.2, §7.3, §12 |
| P41: `SlideDataBuilder` wording imprecise | "Replaces SlideElementParser" | "Bypasses HTML intermediate step; SlideElementParser retained for HTML preview path" |

## 17. v2.2 → v2.3 Change Summary (7 issues fixed)

| Issue | v2.2 | v2.3 |
|---|---|---|
| P42: `images[].chart_type` doesn't exist | P29 fix claimed priority on `images[].chart_type` field, but SmartChartGenerator only writes `{src, alt}` (html_to_ppt.py:496). ImageProvider writes `{src, alt, image_type}` (image_provider.py:55-58). | `_detect_chart_type` uses `image_type=="chart"` + src path patterns; no reliance on non-existent `chart_type` field. Added note about future improvement to `_auto_generate_charts()`. |
| P42b: `_detect_chart_type` missing ChartType values | Only matched pie/bar/line/ranking ("ranking" not a valid ChartType) | Matches all 10 ChartType enum values (BAR, HBAR, BAR_LINE, PIE, LINE, RADAR, SCATTER, BUBBLE, WATERFALL, QUADRANT). Removed invalid "ranking". Order-aware: hbar checked before bar, bar_line before bar. |
| P43: L2 Replace image needs new API | `ImageProvider.enrich_images()` only adds when no images exist (line 36: `if images: return`). L2 replacement can't use it. | Added note: L2 requires new `ImageProvider.replace_image(slide_data, image_index, keyword, image_type)` method. |
| P44+P45: `_replace_slide` uses non-existent python-pptx API | `pptx.part.drop_rel()` and `pptx.presentation.sldIdLst` don't exist in python-pptx public API. | Replaced with realistic Approach A (L4 degradation) and Approach B (XML swap using documented internals: `slide._element`, `slide.part`, `part.rels`). Added python-pptx API caveats. |
| P46: L0 Review level has no section | L0 added to §5.1 table but no dedicated §5.X | Added §5.2 L0: Review — No Modification |
| P49: `_validate_click_level` uses string keys | `INCONSISTENT_MAP` uses string keys like `"modify_table"` instead of `RevisionOpType` | Changed to use `RevisionOpType` enum for consistency with `DEFAULT_LEVEL_MAP` |
| P51: Change chart type data source too manual | §4.3 says "extract data from table_data/items to construct ChartSuggestion" | Changed to call `SmartChartGenerator.analyze_content()` first (reuses existing data extraction logic), then fall back to manual construction if no matching suggestion |
| P29→P42 regression: `_detect_chart_type` claimed non-existent field | P29 in v2.1 added `images[].chart_type` priority, but this field doesn't exist in current pipeline | Removed false claim; documented actual data flow in SmartChartGenerator and ImageProvider |
