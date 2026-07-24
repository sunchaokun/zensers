# PPT模板系统重构设计 v1.3

> 日期: 2026-07-07
> 状态: In Review
> 目标: 将PPT渲染从硬编码位置改为JSON模板驱动，实现专业级行业研究PPT输出
> v1.3修订: 修复10项代码级错误（见附录B）
> v1.2修订: 修复17项代码可行性问题（见附录A）
> v1.1修订: 修复7项设计问题（KPI提取规则、comparison分配、chart_split多图、decoration分层、模板加载机制、P4详细说明、insight_bar source冲突）

## 1. 问题诊断

### 当前架构
```
HTML → SlideElementParser → slide_data[] → _create_pptx_document()
                                              ├── _create_cover_slide()    ← 硬编码Inches()
                                              ├── _create_toc_slide()      ← 硬编码Inches()
                                              ├── _create_content_slide()  ← 硬编码Inches()
                                              ├── _create_data_slide()     ← 硬编码Inches()
                                              ├── _create_findings_slide() ← 硬编码Inches()
                                              └── _create_end_slide()      ← 硬编码Inches()
```

### 6大差距

| # | 差距 | 现状 | 专业报告标准 |
|---|------|------|-------------|
| 1 | 缺少KPI数据卡片 | 纯文字列表 | 大数字+标签+趋势箭头 |
| 2 | 缺少章节分隔页 | 无 | 深蓝背景+编号+标题+摘要 |
| 3 | 缺少图表主导页 | 图只占右半 | 图占80%+底部洞察条 |
| 4 | 缺少对比/时间线页 | 无 | 双栏对比/水平时间线 |
| 5 | 缺少报告规范元素 | 无页码/来源/品牌 | 页码+来源+品牌标识 |
| 6 | 布局不可配置 | 改Python代码 | 改JSON数字 |

## 2. 目标架构

```
HTML → SlideElementParser → slide_data[]
                                  ↓
         TemplateSelector.select_and_enhance(slide_data) → template_name
                                  ↓                              ↓
         template_config = Registry.get(template_name)    slide_data增强(kpi_data等)
                                  ↓
         SlideRenderer.render(slide, slide_data, template_config)
            ├── _render_background(...)
            ├── _render_decoration(layer="bottom" ...)
            ├── _render_slot("title", ...)     ← 通用
            ├── _render_slot("kpi_cards", ...) ← 专用
            ├── _render_slot("items", ...)     ← 通用
            ├── _render_slot("image", ...)     ← 通用
            ├── _render_slot("table", ...)     ← 通用
            └── _render_decoration(layer="top" ...)
```

核心变化：**6个`_create_xxx_slide`方法 → 1个通用渲染器 + 12个JSON模板配置**

## 3. 模板配置规范

### 3.1 配置文件位置

```
config/ppt_templates/
├── cover.json
├── toc.json
├── section_title.json
├── kpi_highlight.json
├── content_left_right.json      # 左文右图
├── content_text_only.json       # 纯文字全宽
├── chart_full.json              # 图表主导
├── chart_split.json             # 双图对比
├── data_table.json              # 表格+图表
├── comparison.json              # 对比分析
├── findings.json
└── end.json
```

### 3.2 配置Schema

每个模板JSON包含4个顶层key：

```json
{
  "meta": {
    "name": "kpi_highlight",
    "display_name": "KPI指标看板",
    "description": "3-4个KPI大数字卡片+底部洞察",
    "min_kpis": 2,
    "max_kpis": 4
  },
  "background": {
    "type": "solid",
    "color": "white"
  },
  "slots": [...],
  "decorations": [...]
}
```

### 3.3 Slot类型定义

Slot是模板中的内容占位符，定义位置、大小、样式：

#### text slot — 标题/文字
```json
{
  "id": "title",
  "type": "text",
  "source": "title",
  "position": { "left": 0.8, "top": 0.3, "width": 11.7, "height": 0.7 },
  "style": {
    "font_size": 24,
    "font_weight": "bold",
    "color": "navy",
    "font": "Microsoft YaHei"
  }
}
```

- `source`: 从slide_data取值的key，支持 `"title"`, `"content"`, `"items"`, `"subtitle"`
- 特殊source `"auto"`: 由渲染器根据上下文填充

#### items slot — 要点列表
```json
{
  "id": "bullet_items",
  "type": "items",
  "source": "items",
  "position": { "left": 0.8, "top": 1.3, "width": 5.6, "height": 5.2 },
  "style": {
    "bullet": "▸",
    "bullet_color": "gold",
    "font_size": 14,
    "color": "text_dark",
    "line_spacing": 6,
    "max_items": 5
  }
}
```

#### image slot — 图片
```json
{
  "id": "chart",
  "type": "image",
  "source": "images",
  "position": { "left": 6.4, "top": 1.6, "width": 6.4, "height": 5.2 },
  "style": {
    "preserve_aspect": true,
    "index": 0
  }
}
```

- `index`: 取images数组的第几个（0=第一个）

#### table slot — 表格
```json
{
  "id": "data_table",
  "type": "table",
  "source": "table_data",
  "position": { "left": 0.8, "top": 1.3, "width": 5.6, "height": "auto" },
  "style": {
    "header_bg": "navy",
    "header_color": "white",
    "row_font_size": 12,
    "stripe": true,
    "stripe_color": "off_white"
  }
}
```

- `height: "auto"`: 根据行数自动计算

#### kpi_cards slot — KPI卡片组（新增）
```json
{
  "id": "kpi_row",
  "type": "kpi_cards",
  "source": "kpi_data",
  "position": { "left": 0.8, "top": 1.5, "width": 11.7, "height": 3.5 },
  "style": {
    "card_bg": "navy",
    "card_gap": 0.4,
    "number_size": 36,
    "number_color": "gold",
    "label_size": 12,
    "label_color": "white",
    "trend_up": "↑",
    "trend_down": "↓",
    "trend_color_up": "4CAF50",
    "trend_color_down": "F44336",
    "max_cards": 4
  }
}
```

KPI卡片从`kpi_data`（预提取的结构化数据）渲染，不再直接从原始`items`提取。
**数据来源链路**：`_build_slide_dict`提取items → `TemplateSelector._detect_kpis()`从items生成kpi_data → 填充到slide_data["kpi_data"] → kpi_cards slot从kpi_data渲染。

**提取规则**：一条item可能含多个数字（如"15.1B USD, up 28.9% YoY"），提取策略：
1. 优先提取带单位的绝对值（15.1B, 2.7M）作为主KPI数字
2. 百分比值(28.9%)作为趋势指标，不作为主数字
3. 标签从item前半段语义提取（取冒号前的部分，或取主语短语）
4. 如果一条item没有绝对值只有百分比，则百分比作为主数字

例如：
- `"Global market grew 28.9% YoY to reach 15.1B USD"` → 数字: `15.1B`, 标签: `Global Market`, 趋势: `↑ 28.9%`
- `"Customer retention rate: 91% for top quartile"` → 数字: `91%`, 标签: `Customer Retention`, 趋势: `None`
- `"AI/ML segment: 2.1B USD, growing 68% YoY"` → 数字: `2.1B`, 标签: `AI/ML Segment`, 趋势: `↑ 68%`

**slide_data新增kpi_data key**：由TemplateSelector._detect_kpis()填充到slide_data中（在select_and_enhance方法中执行），格式：
```python
{"number": "15.1B", "label": "Global Market", "trend": "28.9%", "trend_direction": "up", "original_text": "..."}
```

注意：`trend`存储纯百分比文本（如`"28.9%"`），`trend_direction`存储方向（`"up"`/`"down"`/`None`），渲染时组合为`"↑ 28.9%"`。

kpi_cards slot的source为`"kpi_data"`（预提取后的结构化数据），渲染器从slide_data["kpi_data"]读取。

#### insight_bar slot — 底部洞察条（新增）
```json
{
  "id": "insight",
  "type": "insight_bar",
  "source": "insight_text",
  "position": { "left": 0.8, "top": 5.8, "width": 11.7, "height": 1.0 },
  "style": {
    "bg_color": "navy",
    "icon": "💡",
    "font_size": 13,
    "color": "white"
  }
}
```

- `source`改为`"insight_text"`（专用key），不与`"content"`或`"items"`冲突
- insight_text来源：slide_data中的`insight_text`字段，由content_orchestrator在生成HTML时从`<p>`标签提取摘要性文字
- 如果slide_data无`insight_text`，insight_bar不渲染（优雅降级）

#### comparison slot — 双栏对比（新增）
```json
{
  "id": "compare",
  "type": "comparison",
  "source": "comparison_data",
  "position": { "left": 0.8, "top": 1.3, "width": 11.7, "height": 5.2 },
  "style": {
    "left_title": "Current State",
    "right_title": "Future State",
    "left_color": "navy",
    "right_color": "gold",
    "font_size": 13
  }
}
```

comparison slot从`comparison_data`（预拆分后的结构化数据）渲染，不再直接从原始`items`提取。
**数据来源链路**：`_build_slide_dict`提取items → `TemplateSelector._detect_comparison()`从items生成comparison_data → 填充到slide_data["comparison_data"] → comparison slot从comparison_data渲染。

**分配规则**：items不按奇偶分配（语义会错乱），而是按分隔符拆分：
1. 如果item含`"vs"`/`"对比"`/`"——"`等分隔符，拆成左右两部分
2. 如果items中间有`"---"`分隔行，分隔行前归左栏，后归右栏
3. 如果无分隔符，前半items归左栏，后半归右栏（按数量均分）
4. comparison_data格式：
```python
{
  "left": {"title": "Current State", "items": ["item1", "item2"]},
  "right": {"title": "Future State", "items": ["item3", "item4"]}
}
```
`title`字段来源：优先从分隔符两侧的语义提取（如"A vs B" → left_title="A", right_title="B"）；无分隔符时使用JSON模板中的`left_title`/`right_title`默认值；含`"---"`分隔行时也使用默认值。由TemplateSelector._detect_comparison()填充到slide_data中。

### 3.4 Decorations定义

装饰元素不依赖数据，是固定的视觉元素。每个decoration包含`layer`字段控制渲染层级：

- `"bottom"`: 视觉框架层（背景渐变、侧边条、底部条、标题下划线）— 最底层
- `"top"`: 信息标注层（页码、来源、品牌标识）— 最顶层，覆盖在内容之上

```json
{
  "decorations": [
    { "type": "gradient_bg", "layer": "bottom", "color1": "navy", "color2": "navy_light" },
    { "type": "side_accent", "layer": "bottom", "color": "gold", "width": 0.06 },
    { "type": "footer_bar", "layer": "bottom", "color": "gold", "height": 0.11 },
    { "type": "title_underline", "layer": "bottom", "color": "gold", "width": 4.0, "offset_top": 1.05 },
    { "type": "left_accent", "layer": "bottom", "color": "gold", "width": 0.05, "height": 4.0 },
    { "type": "page_number", "layer": "top", "position": "bottom_right", "color": "text_light", "font_size": 10 },
    { "type": "source_text", "layer": "top", "text": "Source: Internal Research", "position": "bottom_left", "color": "text_light", "font_size": 9 },
    { "type": "branding", "layer": "top", "text": "CONFIDENTIAL", "position": "top_right", "color": "text_light", "font_size": 9 }
  ]
}
```

渲染器按`layer`分组渲染：先渲染`layer="bottom"`的decoration，再渲染slots，最后渲染`layer="top"`的decoration。新增decoration类型只需指定layer，无需修改渲染器代码。

## 4. 12个模板详细设计

### 4.1 cover.json — 封面
- 背景: navy→navy_light渐变
- Slots: title(居中44pt金色), subtitle(居中24pt白色), date(居中18pt白色)
- Decorations: footer_bar(gold), branding

### 4.2 toc.json — 目录
- 背景: off_white
- Slots: title(居中28pt), items(带■编号20pt)
- Decorations: footer_bar, left_accent(gold), page_number

### 4.3 section_title.json — 章节分隔页（新增）
- 背景: navy
- Slots: section_number(左上48pt金色如"01"), title(居中36pt白色), subtitle(居中16pt白色半透明)
- Decorations: footer_bar(gold), 右侧大号章节编号水印

### 4.4 kpi_highlight.json — KPI看板（新增）
- 背景: white
- Slots: title(24pt navy), kpi_cards(3-4个深蓝卡片), insight_bar(底部深蓝洞察条)
- Decorations: side_accent, footer_bar, page_number, source_text

### 4.5 content_left_right.json — 左文右图
- 背景: white
- Slots: title(24pt navy), items(左42%宽14pt), image(右52%宽)
- Decorations: side_accent, footer_bar, title_underline, page_number, source_text

### 4.6 content_text_only.json — 纯文字全宽
- 背景: white
- Slots: title(24pt navy), items(全宽14pt)
- Decorations: side_accent, footer_bar, title_underline, page_number, source_text

### 4.7 chart_full.json — 图表主导（新增）
- 背景: white
- Slots: title(24pt navy), image(占80%高度居中), insight_bar(底部洞察条)
- Decorations: side_accent, footer_bar, title_underline, page_number, source_text

### 4.8 chart_split.json — 双图对比（新增）
- 背景: white
- Slots: title(24pt navy), image_1(左半, source=images, index=0), image_2(右半, source=images, index=1), insight_bar(底部)
- Decorations: side_accent, footer_bar, title_underline, page_number, source_text
- **多图分配**：image slot的`index`字段指定取images数组的第几个。chart_split模板定义两个image slot，index分别为0和1。SlideRenderer按index从slide_data["images"]取对应图片。

### 4.9 data_table.json — 表格+图表
- 背景: white
- Slots: title(24pt navy), table(左42%), image(右52%)
- Decorations: side_accent, footer_bar, title_underline, page_number, source_text

### 4.10 comparison.json — 对比分析（新增）
- 背景: white
- Slots: title(24pt navy), comparison(双栏), image(右半可选)
- Decorations: side_accent, footer_bar, title_underline, page_number, source_text

### 4.11 findings.json — 关键发现
- 背景: white
- Slots: title(24pt navy), items(✓前缀16pt金色), image(右半可选)
- Decorations: side_accent, footer_bar, title_underline, page_number, source_text

### 4.12 end.json — 结束页
- 背景: navy
- Slots: title(居中44pt金色), subtitle(居中28pt白色)
- Decorations: footer_bar(white), branding

## 5. 智能模板选择器

### 5.1 模板加载机制

`TemplateRegistry`负责加载和管理JSON模板配置：

```python
class TemplateRegistry:
    """模板注册表，加载和管理JSON模板配置（模块级单例）"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls, template_dir: str = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, template_dir: str = None):
        if TemplateRegistry._initialized:
            return
        TemplateRegistry._initialized = True
        if template_dir is None:
            env_dir = os.environ.get("PPT_TEMPLATE_DIR")
            if env_dir and os.path.isdir(env_dir):
                template_dir = env_dir
            else:
                base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                candidate = os.path.join(base, "config", "ppt_templates")
                if os.path.isdir(candidate):
                    template_dir = candidate
                else:
                    template_dir = os.path.join(os.getcwd(), "config", "ppt_templates")
        self.template_dir = template_dir
        self._templates = {}
        self._load_all()
    
    def _load_all(self):
        """启动时一次性加载所有JSON模板"""
        for fname in os.listdir(self.template_dir):
            if fname.endswith(".json"):
                path = os.path.join(self.template_dir, fname)
                with open(path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                name = config.get("meta", {}).get("name", fname.replace(".json", ""))
                self._templates[name] = config
    
    def get(self, name: str) -> Dict:
        """获取模板配置，不存在则抛KeyError"""
        return self._templates[name]
    
    def list_templates(self) -> List[str]:
        """列出所有可用模板名"""
        return list(self._templates.keys())
    
    def reload(self, name: str = None):
        """热重载：重新加载指定模板或全部模板"""
        if name:
            fname = f"{name}.json"
            path = os.path.join(self.template_dir, fname)
            with open(path, "r", encoding="utf-8") as f:
                self._templates[name] = json.load(f)
        else:
            self._templates.clear()
            self._load_all()
    
    @classmethod
    def _reset(cls):
        """重置单例状态（仅用于测试）。生产代码不应调用此方法。"""
        cls._instance = None
        cls._initialized = False
```

**打包兼容**：当项目打包为exe/whl时，`__file__`路径可能不同。解决方案：
1. 优先使用环境变量`PPT_TEMPLATE_DIR`（如有）
2. 其次使用`__file__`相对路径
3. 最后fallback到当前工作目录下的`config/ppt_templates/`

### 5.2 TemplateSelector

`TemplateSelector`根据slide_data的内容特征自动选择最合适的模板：

```python
class TemplateSelector:
    def select_and_enhance(self, slide_data: Dict, section_index: int = 0) -> str:
        """选择模板并增强slide_data（填充kpi_data、comparison_data等）。
        
        必须在SlideRenderer.render()之前调用此方法，确保slide_data包含所有渲染所需的字段。
        """
        template_name = self._select(slide_data, section_index)
        self._enhance_slide_data(slide_data, template_name, section_index)
        return template_name
    
    def _select(self, slide_data: Dict, section_index: int = 0) -> str:
        slide_type = slide_data.get("slide_type", "content")
        items = slide_data.get("items", [])
        images = slide_data.get("images", [])
        table = slide_data.get("table_data", [])
        content = slide_data.get("content", "")
        
        # 固定类型直接映射（兼容连字符和下划线命名）
        if slide_type == "cover":              return "cover"
        if slide_type == "toc":                return "toc"
        if slide_type == "end":                return "end"
        if slide_type in ("section_title", "section-title"):
            return "section_title"
        
        if slide_type == "findings":
            return "findings"
        
        if slide_type == "data" and table:
            return "data_table"
        
        # 智能选择（需要预检测数据）
        kpis = self._detect_kpis(items)
        has_comparison = bool(items) and self._detect_comparison(items)
        
        # KPI检测: items中含数字+百分比/趋势词 → kpi_highlight
        if kpis and len(kpis) >= 2 and len(kpis) <= 4:
            return "kpi_highlight"
        
        # 双图检测
        if len(images) >= 2 and not items and not table:
            return "chart_split"
        
        # 图表主导: 有图但无文字要点
        if images and not items and not table:
            return "chart_full"
        
        # 对比检测: items含"vs"/"compared"/"while"/"而"/"对比"
        if has_comparison:
            return "comparison"
        
        # data类型无table时，按图表主导处理
        if slide_type == "data" and images:
            return "chart_full"
        
        # 左文右图
        if items and images:
            return "content_left_right"
        
        # 纯文字
        return "content_text_only"
    
    def _enhance_slide_data(self, slide_data: Dict, template_name: str, section_index: int):
        """根据选中的模板，向slide_data填充渲染所需的增强字段。"""
        items = slide_data.get("items", [])
        
        if template_name == "kpi_highlight":
            kpis = self._detect_kpis(items)
            if kpis:
                # 标签为空时，用slide title回填
                slide_title = slide_data.get("title", "")
                for kpi in kpis:
                    if not kpi.get("label") and slide_title:
                        kpi["label"] = slide_title[:30]
                slide_data["kpi_data"] = kpis
        
        if template_name == "comparison":
            comp = self._detect_comparison(items)
            if comp:
                slide_data["comparison_data"] = comp
        
        if template_name == "section_title":
            slide_data["section_number"] = section_index
            if not slide_data.get("section_summary"):
                content = slide_data.get("content", "")
                slide_data["section_summary"] = content[:100] if content else ""
        
        # insight_text: 从content字段自动提取（取最后一句或前120字符）
        if template_name in ("kpi_highlight", "chart_full", "chart_split"):
            if not slide_data.get("insight_text"):
                content = slide_data.get("content", "")
                if content:
                    sentences = re.split(r'[.!?。！？]\s*', content)
                    slide_data["insight_text"] = sentences[-1].strip()[:120] if sentences else content[:120]
    
    def _detect_kpis(self, items: List[str]) -> List[Dict]:
        """从items中检测KPI数据点
        
        提取规则（按优先级）：
        1. 优先提取带单位的绝对值（15.1B, 2.7M）作为主KPI数字
        2. 百分比值(28.9%)作为趋势指标，不作为主数字
        3. 标签提取：优先取冒号前的部分；否则取slide_data["title"]；否则取数字前最后一个名词短语
        4. 如果一条item没有绝对值只有百分比，则百分比作为主数字
        5. 年份(19xx/20xx)后紧跟B/M/K不作为KPI，防止"2024B"误匹配
        6. 单个数字紧跟B/M/K但无小数点且无货币后缀时（如"2B released"），视为版本号/阶段号，跳过
        """
        import re
        kpis = []
        for item in items:
            kpi = {}
            # 1. 检测绝对值（带单位），排除年份+字母
            # 策略：小数点数字或2位以上数字才视为KPI量级；单数字需带货币后缀
            abs_match = re.search(
                r'(?<!\d)(?!(?:19|20)\d{2})'
                r'((?:\d+\.\d+|\d{2,})\s*(?:万亿|亿|万|[BMK])'
                r'(?:\s*(?:USD|CNY|EUR|元|美元))?'
                r'|\d\s*[BMK]\s*(?:USD|CNY|EUR|元|美元))'
                r'\b',
                item, re.I
            )
            # 2. 检测百分比值
            pct_match = re.search(r'(\d+\.?\d*)\s*%', item)
            
            if abs_match:
                # 提取纯数字+单位部分（去除货币后缀）
                num_unit = re.match(r'([\d.]+)\s*(万亿|亿|万|[BMK])', abs_match.group(1), re.I)
                if num_unit:
                    kpi["number"] = num_unit.group(1) + num_unit.group(2)
                else:
                    kpi["number"] = abs_match.group(1).split()[0]  # 取空格前部分
                # 百分比作为趋势
                if pct_match:
                    kpi["trend"] = pct_match.group(0)
                else:
                    kpi["trend"] = None
            elif pct_match:
                kpi["number"] = pct_match.group(0)
                kpi["trend"] = None
            else:
                continue  # 无数字，跳过
            
            # 3. 提取标签 — 三级优先策略
            # 优先级1: 冒号前
            if ":" in item:
                kpi["label"] = item.split(":")[0].strip()[:30]
            # 优先级2: 无冒号但有slide title时，后续由_enhance_slide_data填充
            # 优先级3: 取数字前的末尾名词短语（过滤介词/连词等）
            else:
                num_pos = item.find(kpi["number"])
                prefix = item[:num_pos].strip()
                # 过滤常见介词/连词
                stop_words = {'to','up','from','of','the','a','an','in','on','at','by','for','and','or','with','as','is','was','reached','hit','grew','gained','climbed','reach','yoy','cagr','per','each'}
                words = re.split(r'[,;；\s]+', prefix)
                # 从后向前取非停用词，且排除纯数字/百分比token
                meaningful = [w for w in words if w.lower() not in stop_words and len(w) > 1 and not re.match(r'^[\d.]+%?$', w)]
                kpi["label"] = " ".join(meaningful[-3:])[:30] if meaningful else ""
            
            # 4. 检测趋势方向
            if re.search(r'(grew|increased|up|rose|surged|增长|上升)', item, re.I):
                kpi["trend_direction"] = "up"
            elif re.search(r'(declined|decreased|down|fell|dropped|下降|减少)', item, re.I):
                kpi["trend_direction"] = "down"
            else:
                kpi["trend_direction"] = None
            
            kpi["original_text"] = item
            kpis.append(kpi)
        return kpis
    
    def _detect_comparison(self, items: List[str]) -> Optional[Dict]:
        """从items中检测对比结构并拆分为左右栏
        
        拆分规则（按优先级）：
        1. 含"vs"/"对比"/"——"分隔符的item，拆成左右两部分
        2. items中间有"---"分隔行，前归左栏后归右栏
        3. 无分隔符时，按数量均分
        
        返回None表示无对比结构（items为空或无法拆分）。
        """
        if not items:
            return None
        
        left_items, right_items = [], []
        left_title, right_title = None, None
        separator_found = False
        
        # 规则2: 检测"---"分隔行
        if any(item.strip() == "---" for item in items):
            sep_idx = next(i for i, item in enumerate(items) if item.strip() == "---")
            left_items = items[:sep_idx]
            right_items = items[sep_idx+1:]
            return {
                "left": {"title": "", "items": left_items},
                "right": {"title": "", "items": right_items}
            }
        
        # 规则1: 检测含分隔符的item
        unmatched = []
        for item in items:
            matched = False
            for sep in [" vs ", " VS ", " vs. ", "对比", "——"]:
                if sep in item:
                    parts = item.split(sep, 1)
                    left_part = parts[0].strip()
                    right_part = parts[1].strip()
                    left_items.append(left_part)
                    right_items.append(right_part)
                    # 首次匹配时提取标题（标题不重复放入items）
                    if not separator_found:
                        left_title = left_part[:30]
                        right_title = right_part[:30]
                        # 从items列表中移除标题项（避免标题和首项重复）
                        left_items.pop()
                        right_items.pop()
                        # 标题本身作为首项保留在标题字段，不放入items
                    separator_found = True
                    matched = True
                    break
            if not matched:
                unmatched.append(item)
        
        if separator_found:
            # 未匹配的item追加到较短的一侧
            for item in unmatched:
                if len(left_items) <= len(right_items):
                    left_items.append(item)
                else:
                    right_items.append(item)
            return {
                "left": {"title": left_title or "", "items": left_items},
                "right": {"title": right_title or "", "items": right_items}
            }
        
        # 规则3: 均分
        mid = len(items) // 2
        if mid == 0:
            return None  # 只有0-1个item，不适合对比展示
        return {
            "left": {"title": "", "items": items[:mid]},
            "right": {"title": "", "items": items[mid:]}
        }
```

## 6. 渲染引擎

### 6.1 SlideRenderer类

```python
class SlideRenderer:
    """通用PPT渲染引擎，根据模板配置渲染slide"""
    
    def __init__(self, design: Dict[str, str]):
        self.design = design  # DESIGN颜色字典
    
    def render(self, slide, slide_data: Dict, template: Dict, styles: Dict, page_num: int = 0):
        """主渲染入口"""
        decorations = template.get("decorations", [])
        
        # 1. 渲染背景（最底层）
        self._render_background(slide, template.get("background", {}))
        
        # 2. 渲染底层装饰（layer="bottom" — 视觉框架层）
        for dec in decorations:
            if dec.get("layer") != "top":  # 无layer或layer="bottom"均归底层
                self._render_decoration(slide, dec, styles, page_num)
        
        # 3. 渲染slots（内容层 — 在装饰之上）
        for slot in template.get("slots", []):
            self._render_slot(slide, slot, slide_data, styles)
        
        # 4. 渲染顶层装饰（layer="top" — 信息标注层，在内容之上）
        for dec in decorations:
            if dec.get("layer") == "top":
                self._render_decoration(slide, dec, styles, page_num)
    
    def _render_slot(self, slide, slot: Dict, slide_data: Dict, styles: Dict):
        """根据slot类型分发到专用渲染器。所有slot渲染器统一接受(slide, slot, slide_data, styles)参数。"""
        slot_type = slot.get("type", "text")
        if slot_type == "text":         self._render_text_slot(slide, slot, slide_data, styles)
        elif slot_type == "items":      self._render_items_slot(slide, slot, slide_data, styles)
        elif slot_type == "image":      self._render_image_slot(slide, slot, slide_data, styles)
        elif slot_type == "table":      self._render_table_slot(slide, slot, slide_data, styles)
        elif slot_type == "kpi_cards":  self._render_kpi_cards_slot(slide, slot, slide_data, styles)
        elif slot_type == "insight_bar": self._render_insight_bar_slot(slide, slot, slide_data, styles)
        elif slot_type == "comparison": self._render_comparison_slot(slide, slot, slide_data, styles)
    
    def _resolve_color(self, color_str: str) -> str:
        """解析颜色值：命名色从DESIGN字典映射，hex色直接返回。"""
        if color_str in self.design:
            return self.design[color_str]
        return color_str  # assume hex like "4CAF50"
    
    def _render_image_slot(self, slide, slot: Dict, slide_data: Dict, styles: Dict):
        """渲染图片slot，支持index字段指定取images数组的第几个。"""
        images = slide_data.get(slot.get("source", "images"), [])
        idx = slot.get("style", {}).get("index", 0)
        if idx >= len(images):
            return  # index越界，优雅跳过
        img_info = images[idx]
        pos = slot.get("position", {})
        # ... 具体渲染逻辑
    
    def _render_table_slot(self, slide, slot: Dict, slide_data: Dict, styles: Dict):
        """渲染表格slot，height="auto"时按行数自动计算。"""
        table_data = slide_data.get(slot.get("source", "table_data"), [])
        if not table_data:
            return
        pos = slot.get("position", {})
        height = pos.get("height", "auto")
        if height == "auto":
            row_height = 0.4  # 基础行高（英寸）
            height = len(table_data) * row_height
        # ... 具体渲染逻辑
```

### 6.2 KPI卡片渲染细节

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  15.1B       │  │  28.9%      │  │  91%         │  │  42%        │
│  ↑ 28.9%     │  │  ↑ YoY      │  │  Retention   │  │  ↑ from 28% │
│  Market Size │  │  Growth     │  │  Rate        │  │  SMB Adopt  │
└─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘
```

每个卡片实现：
1. 深蓝圆角矩形背景（python-pptx用add_shape + MSO_SHAPE.ROUNDED_RECTANGLE）
2. 大数字：36pt金色，居中偏上
3. 趋势箭头：↑绿色/↓红色，16pt，紧跟数字
4. 标签文字：12pt白色，居中偏下

### 6.3 章节分隔页渲染细节

```
┌──────────────────────────────────────────────────┐
│  (navy gradient background)                       │
│                                                   │
│  01                                    01 (水印)  │
│  ──                                              │
│  Executive Summary                               │
│  Market overview and key performance indicators   │
│                                                   │
│  ═══════════════════════════════════════════════  │ (gold footer)
└──────────────────────────────────────────────────┘
```

### 6.4 图表主导页渲染细节

```
┌──────────────────────────────────────────────────┐
│ ▌ Revenue by Region                              │
│ ▌────────────────────────────────                │
│                                                   │
│  ┌─────────────────────────────────────────────┐ │
│  │                                             │ │
│  │            [Chart - 80% height]             │ │
│  │                                             │ │
│  └─────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────┐ │
│  │ 💡 Asia Pacific leads growth at 35% YoY     │ │ (navy insight bar)
│  └─────────────────────────────────────────────┘ │
│ ═════════════════════════════════════════════════ │
└──────────────────────────────────────────────────┘
```

## 7. 报告规范元素

### 7.1 页码
- 位置: 右下角，footer_bar上方
- 格式: "第 X 页" 或 "X / N"
- 样式: 10pt text_light
- 排除: cover页不显示

### 7.2 来源标注
- 位置: 左下角，footer_bar上方
- 格式: "Source: Internal Research | Data as of 2024-12"
- 样式: 9pt text_light
- 排除: cover/end页不显示

### 7.3 品牌标识
- 位置: 右上角
- 格式: "CONFIDENTIAL" 或公司名
- 样式: 9pt text_light
- 仅: cover/end页显示

## 8. 数据流增强

### 8.1 slide_data扩展

当前slide_data keys: `slide_type, title, content, items, table_data, images`

新增keys:
- `section_number: int` — 章节编号（由TemplateSelector._enhance_slide_data从section_index参数填充）
- `section_summary: str` — 章节一句话摘要（由TemplateSelector._enhance_slide_data从content截取，或从HTML data-section-summary属性提取）
- `kpi_data: List[Dict]` — 预提取的KPI数据点（由TemplateSelector._detect_kpis在select_and_enhance中填充）
- `comparison_data: Dict` — 预拆分的对比数据（由TemplateSelector._detect_comparison在select_and_enhance中填充）
- `insight_text: str` — 底部洞察条文字（由TemplateSelector._enhance_slide_data从content自动提取，或由content_orchestrator在HTML中通过data-insight-text属性提供）
- `source_text: str` — 来源标注文字（默认"Source: Internal Research"，可由HTML data-source属性覆盖）
- `page_total: int` — 总页数（由_convert_pptx_document在渲染循环前计算slides总数填充）

**数据来源实现路径**：

| key | 填充时机 | 填充位置 |
|------|----------|----------|
| `kpi_data` | select_and_enhance | TemplateSelector._enhance_slide_data |
| `comparison_data` | select_and_enhance | TemplateSelector._enhance_slide_data |
| `insight_text` | select_and_enhance | TemplateSelector._enhance_slide_data (自动提取) / content_orchestrator (HTML属性) |
| `section_number` | select_and_enhance | TemplateSelector._enhance_slide_data (从section_index参数) |
| `section_summary` | select_and_enhance | TemplateSelector._enhance_slide_data (从content截取) / content_orchestrator (HTML属性) |
| `source_text` | _build_slide_dict | base_parser (从HTML data-source属性) / 默认值 |
| `page_total` | _create_pptx_document | html_to_ppt (渲染循环前计算) |

### 8.2 _build_slide_dict增强

在`_build_slide_dict`中：

1. 修复现有BUG：`extra_tables`引用未初始化的`slide`变量（line 532）
2. 新增KPI预提取
3. 新增source_text提取

```python
def _build_slide_dict(self, elements, attrs=None):
    attrs = attrs or {}
    slide_type = attrs.get("data-type", "content")
    
    title = ""
    content_parts = []
    items = []
    table_data = []
    images = []
    extra_tables = []  # 修复: 提前声明，避免引用未初始化的slide
    
    for elem in elements:
        etype = elem.get("type", "")
        
        # ... 现有heading/paragraph/list_item/image处理不变 ...
        
        elif etype == "table":
            # ... 现有table_rows构建不变 ...
            if table_rows:
                if table_data:
                    extra_tables.append(table_rows)  # 修复: 不再引用slide
                else:
                    table_data = table_rows
    
    slide = {
        "slide_type": slide_type,
        "title": title,
    }
    
    if content_parts:  slide["content"] = "\n".join(content_parts)
    if items:          slide["items"] = items
    if table_data:     slide["table_data"] = table_data
    if images:         slide["images"] = images
    if extra_tables:   slide["extra_tables"] = extra_tables  # 新增: 正确附加
    
    # 新增: source_text从HTML属性提取
    source = attrs.get("data-source", "")
    if source:
        slide["source_text"] = source
    
    return slide
```

注意：KPI预提取不再在`_build_slide_dict`中进行，改为在`TemplateSelector.select_and_enhance`中执行。理由：KPI检测需要结合模板选择策略（如只有2-4个KPI才选kpi_highlight），属于选择逻辑而非解析逻辑。

### 8.3 _group_by_sections增强

在section_start时记录章节编号：

```python
section_counter = 0
for elem in elements:
    if etype in ("section_start", "div_start"):
        section_counter += 1
        current_attrs = elem.get("attrs", {})
        current_attrs["_section_number"] = section_counter
```

## 9. 迁移策略

### 9.1 兼容性保证

- `HTMLToPPTConverter`的`convert()`接口不变
- 现有6种slide_type继续工作（通过TemplateSelector映射到对应模板）
- 新slide_type（section_title, kpi_highlight, chart_full, chart_split, comparison）通过data-type属性启用

### 9.2 渐进迁移步骤

| Phase | 内容 | 风险 |
|-------|------|------|
| P0 | 修复现有BUG：_build_slide_dict中extra_tables引用未初始化slide变量（line 532） | 低（纯修复，不改变功能） |
| P1 | 创建SlideRenderer + TemplateSelector + 12个JSON模板 | 低（新增代码，不改旧代码） |
| P2 | _create_pptx_document切换到新渲染路径 | 中（核心路径切换） |
| P3 | 删除旧的_create_xxx_slide方法 | 低（P2验证后清理） |
| P4 | content_orchestrator生成新slide_type HTML | 中（上游改动） |

P4详细说明：
1. **命名兼容**：TemplateSelector需兼容`"section-title"`（连字符）和`"section_title"`（下划线），同时在P4中建议将content_orchestrator逐步改为下划线命名
2. **新增HTML类型**：content_orchestrator需新增`_render_kpi_slide()`、`_render_comparison_slide()`、`_render_chart_full_slide()`、`_render_chart_split_slide()`方法
3. **section_title增强**：当前`_render_section_slides()`(line 1275)生成的section-title HTML需增加`data-section-number`和`data-section-summary`属性
4. **KPI触发条件**：当section内容含3+个数字+百分比组合时，自动生成`data-type="kpi_highlight"`的slide
5. **comparison触发条件**：当section标题含"vs"/"对比"/"comparison"关键词时，生成`data-type="comparison"`的slide
6. **insight_text传递**：content_orchestrator在生成chart_full/kpi_highlight类型HTML时，通过`data-insight-text`属性传递洞察文字

注意：原P5（增强slide_data）已合并到P2中——`select_and_enhance`在P2调用时即填充kpi_data/comparison_data/insight_text/section_number/section_summary。page_total由P2的渲染循环前计算填充。source_text由P0的_build_slide_dict修复填充。不再需要独立P5阶段。

### 9.3 回退方案

P2切换时保留旧方法，通过feature flag控制：

```python
USE_TEMPLATE_RENDERER = True  # 切换为False回退到旧路径

for slide_data in slides:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    
    if USE_TEMPLATE_RENDERER:
        template_name = selector.select_and_enhance(slide_data, section_index)
        template = registry.get(template_name)
        renderer.render(slide, slide_data, template, styles, page_num)
    else:
        # 旧的_create_xxx_slide分发
        slide_type = slide_data.get("slide_type", "content")
        if slide_type == "cover": self._create_cover_slide(...)
        ...
```

## 10. 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `src/converters/slide_renderer.py` | 新增 | SlideRenderer通用渲染引擎 |
| `src/converters/template_selector.py` | 新增 | TemplateSelector智能选择器 + TemplateRegistry模板注册表 |
| `config/ppt_templates/*.json` | 新增(12个) | 模板配置文件 |
| `src/converters/html_to_ppt.py` | 重构 | _create_pptx_document切换到新路径 |
| `src/converters/base_parser.py` | 增强+修复 | 修复extra_tables NameError BUG，_build_slide_dict增加source_text提取 |
| `src/content/content_orchestrator.py` | 增强 | section-title→section_title命名统一，新增kpi_highlight/comparison等HTML生成 |
| `tests/unit/test_slide_renderer.py` | 新增 | 渲染引擎测试 |
| `tests/unit/test_template_selector.py` | 新增 | 模板选择器+注册表测试 |
| `tests/unit/test_kpi_detection.py` | 新增 | KPI检测+comparison拆分测试 |

## 11. 验收标准

1. **12种模板全部可渲染** — 每种模板有对应测试用例
2. **KPI卡片正确提取和渲染** — 从"Market grew 28.9% to 15.1B"提取出数字+趋势，标签不含介词/连词
3. **章节分隔页正确显示** — 编号+标题+摘要
4. **页码/来源/品牌正确** — 内容页有页码，cover/end无页码
5. **向后兼容** — 现有6种slide_type输出与重构前视觉一致
6. **JSON配置可热改** — 修改JSON无需改Python代码即可调整布局
7. **高密度数据测试通过** — 12+ items正确拆分，KPI页、图表主导页正确选择
8. **现有测试无新增失败** — P0修复后现有测试状态不得恶化（当前有14个已知失败，需记录但不阻塞）
9. **section-title兼容性** — `"section-title"`（连字符）和`"section_title"`（下划线）均可正确识别
10. **chart_split越界保护** — images不足2张时不崩溃，优雅跳过
11. **_detect_comparison不丢数据** — 含分隔符的items和不含分隔符的items均被正确分配
12. **KPI年份误匹配防护** — "2024B"等年份+字母组合不触发KPI检测
13. **KPI标签质量** — 标签不含介词/连词等停用词，空标签时用slide title回填

## 附录A: v1.2修订问题清单

| # | 问题 | 严重性 | 修复措施 |
|---|------|--------|---------|
| 1 | `_detect_comparison`中未匹配item被静默丢弃 | 阻断 | 用unmatched列表收集，追加到较短侧 |
| 2 | `_build_slide_dict`中extra_tables引用未初始化slide变量(line 532) | 阻断 | 提前声明extra_tables=[]，slide构造后附加 |
| 3 | kpi_cards slot JSON示例source="items"与说明source="kpi_data"矛盾 | 阻断 | JSON统一为source="kpi_data" |
| 4 | comparison slot JSON示例source="items"与说明source="comparison_data"矛盾 | 阻断 | JSON统一为source="comparison_data" |
| 5 | TemplateRegistry假单例——_instance类变量从未赋值 | 阻断 | 用__new__+_initialized实现真单例 |
| 6 | section-title(连字符)与section_title(下划线)命名不匹配 | 严重 | select()中兼容两种命名 |
| 7 | _detect_kpis正则(B\|M\|K)误匹配英文词中字母 | 严重 | 添加\b词边界，长单位优先匹配 |
| 8 | _detect_kpis中kpi["number"]使用group(0)包含货币后缀 | 中 | 改用group(1)+group(2)只取数字+单位 |
| 9 | insight_text无数据来源实现 | 严重 | TemplateSelector._enhance_slide_data中自动提取 |
| 10 | _detect_comparison返回数据缺少title字段，与comparison_data格式不一致 | 严重 | 返回数据增加title字段，从分隔符两侧提取 |
| 11 | _detect_comparison([])返回空dict仍为truthy，误选comparison模板 | 严重 | items为空时返回None，仅1个item时均分结果mid=0也返回None |
| 12 | select()中kpis结果未写入slide_data | 严重 | 改为select_and_enhance()，在方法中填充kpi_data等 |
| 13 | decoration渲染按type名称硬编码分组，扩展性差 | 中 | 改用layer字段分组渲染 |
| 14 | chart_split双图index越界风险 | 中 | _render_image_slot检查index边界 |
| 15 | table slot height="auto"实现未定义 | 中 | 定义auto计算公式: rows * 0.4 |
| 16 | 颜色值格式不统一（命名色vs hex） | 中 | 增加_resolve_color方法 |
| 17 | slide_type="data"无table时fallback不当 | 中 | 增加data+images→chart_full的判断 |

## 附录B: v1.3修订问题清单

| # | 问题 | 严重性 | 修复措施 | 验证方式 |
|---|------|--------|---------|---------|
| 1 | `_render_slot`分发时未传`styles`参数给`_render_image_slot`和`_render_table_slot` | 阻断 | 统一所有slot渲染器签名为`(self, slide, slot, slide_data, styles)`，`_render_slot`分发时传入styles | 代码审查 |
| 2 | `_detect_kpis`正则匹配"2024B"等年份+字母组合为KPI | 阻断 | 添加年份排除`(?!(?:19\|20)\d{2})`，单数字+单位需带货币后缀 | 测试"From 2024B to 2025"不匹配 |
| 3 | `_detect_kpis`标签提取产生"YoY to reach"、"up"等无意义标签 | 严重 | 引入停用词过滤，空标签时用slide title回填 | 测试"up 15%"标签非"up" |
| 4 | `_detect_comparison`中vs分隔符的标题和首项重复（"Cloud"既是title又是items[0]） | 严重 | 提取标题时从items列表中移除该条目 | 测试["Cloud vs On-prem"] → title="Cloud"/items=[] |
| 5 | TemplateRegistry单例无reset方法，无法进行单元测试 | 严重 | 添加`@classmethod _reset()`方法 | 测试中调用_reset()后可重新初始化 |
| 6 | decoration layer判断`dec.get("layer","bottom")=="top"`语义混乱 | 中 | 改为`dec.get("layer")!="top"`和`dec.get("layer")=="top"` | 代码审查 |
| 7 | P5阶段与P2重复（select_and_enhance已填充所有增强字段） | 中 | 合并P5到P2，删除独立P5阶段 | 迁移步骤中无P5 |
| 8 | `_enhance_slide_data`中kpi标签为空时无回填机制 | 中 | 标签为空时用slide_data["title"]回填 | 测试无冒号item的标签提取 |
| 9 | `Optional`类型在TemplateSelector代码中使用但未导入 | 低 | 文件头部`from typing import Optional, Dict, List` | 代码审查 |
| 10 | `_detect_comparison`中unmatched items按"较短侧"分配语义不够明确 | 低 | 保留此策略并添加注释说明这是平衡策略 | 文档说明 |
