# xueqiu 旧路径清理方案

> 日期: 2026-07-06
> 状态: 执行方案
> 前置: Phase 1 基础设施已落地（discovery.py, base.py 增强, registry.py 增强, xueqiu/SKILL.md）

---

## 1. 目标

将 xueqiu 的注册/路由数据来源从**硬编码散布在 8 个文件**切换为**SKILL.md 自描述 + discovery 自动构建**，同时删除 `generic_agent.py` 中的 xueqiu 专用分支（`_infer_xueqiu_actions`、topic fallback 硬编码、execute 参数分支），替换为通用的 manifest 驱动逻辑。

清理完成后，xueqiu 的全部元数据来自 `src/skills/xueqiu/SKILL.md`，运行时行为由 `Skill.infer_actions()` / `Skill.resolve_identifier()` / `SkillRegistry.get_by_capability()` 驱动。

---

## 2. 不动项

以下文件/条目**不删除、不修改**——它们不纯粹是 xueqiu 注册触点，而是通用基础设施：

| 文件 | 条目 | 原因 |
|------|------|------|
| `src/skills/analysis/xueqiu_skill.py` | 整个文件 | xueqiu 的**实现代码**，不是注册触点。`src/skills/xueqiu/skill.py` 已 re-export 它，旧文件暂不删除（其他模块可能直接 import） |
| `src/skills/analysis/__init__.py` | `from .xueqiu_skill import XueqiuSkill` | 其他模块（如 orchestrator.py）可能直接从 `src.skills.analysis` import。清理 orchestrator 后此条保留，作为兼容性 re-export |
| `src/core/search_quality_filter.py` L79 | `"xueqiu.com"` 域名白名单 | 搜索质量评分，与 skill 注册无关 |
| `src/skills/web_scraper_skill.py` L21 | `"xueqiu.com"` JS_DOMAINS | 爬虫 JS 渲染配置，与 skill 注册无关 |

---

## 3. 清理操作清单

按依赖顺序排列，每步标注**风险**和**验证方法**。

### 3.1 `src/core/agents/generic_agent.py` — 通用化替换（高风险）

**3.1.1 删除 `_infer_xueqiu_actions` 方法**（L2717-2739）

用 `Skill.infer_actions()` 通用方法替代。调用点在 L2331-2332：

```python
# 旧代码 (L2331-2332)
if skill_name == "xueqiu":
    actions = self._infer_xueqiu_actions(aspect, symbol)
else:
    actions = self._infer_stock_actions(aspect)

# 新代码
skill_manifest = self._skill_registry.get_manifest(skill_name) if hasattr(self, '_skill_registry') else None
if skill_manifest and skill_manifest.action_rules:
    stock_skill_instance = self._skill_registry.get(skill_name)
    if stock_skill_instance:
        stock_skill_instance._manifest = skill_manifest
        actions = stock_skill_instance.infer_actions(aspect, symbol)
    else:
        actions = self._infer_stock_actions(aspect)
else:
    actions = self._infer_stock_actions(aspect)
```

**3.1.2 删除 xueqiu topic fallback 硬编码**（L2319-2326）

用 `Skill.resolve_identifier()` 通用方法替代：

```python
# 旧代码 (L2319-2326)
if skill_name == "xueqiu" and topic:
    chinese_match = re.search(r'[\u4e00-\u9fff]+', topic)
    if chinese_match:
        symbols = [chinese_match.group(0)]
        ...

# 新代码
if not symbols:
    skill_manifest = self._skill_registry.get_manifest(skill_name) if hasattr(self, '_skill_registry') else None
    if skill_manifest and skill_manifest.supports_topic_fallback and topic:
        stock_skill_instance = self._skill_registry.get(skill_name)
        if stock_skill_instance:
            stock_skill_instance._manifest = skill_manifest
            identifier = stock_skill_instance.resolve_identifier(topic, aspect)
            if identifier:
                symbols = [identifier]
                logger.info(
                    f"GenericAgent {self.agent_id}: {skill_name} topic fallback "
                    f"→ symbol='{identifier}'"
                )
```

**3.1.3 删除 xueqiu execute 参数分支**（L2337-2345）

用 manifest 的 `action_param_map` 通用构建 execute kwargs：

```python
# 旧代码 (L2337-2345)
if skill_name == "xueqiu":
    if action == "search_and_quote":
        skill_result = await stock_skill.execute(action=action, query=symbol)
    else:
        skill_result = await stock_skill.execute(action=action, symbol=symbol)
else:
    skill_result = await stock_skill.execute(action=action, symbol=symbol)

# 新代码
skill_manifest = self._skill_registry.get_manifest(skill_name) if hasattr(self, '_skill_registry') else None
if skill_manifest and skill_manifest.action_param_map and action in skill_manifest.action_param_map:
    param_map = skill_manifest.action_param_map[action]
    exec_kwargs = {"action": action}
    for param_name, source in param_map.items():
        if source == "symbol":
            exec_kwargs[param_name] = symbol
        elif source == "query":
            exec_kwargs[param_name] = symbol
        else:
            exec_kwargs[param_name] = symbol
    skill_result = await stock_skill.execute(**exec_kwargs)
else:
    skill_result = await stock_skill.execute(action=action, symbol=symbol)
```

**3.1.4 删除 `_infer_xueqiu_actions` 方法定义**（L2717-2739）

确认已无调用点后删除整个方法。

### 3.2 `src/core/decomposition/strategies.py` — xueqiu 条目保留（低风险）

**注意**：`strategies.py` 中的硬编码 dict 暂时保留，不删除。原因：
1. 当前 Phase 1 只是**叠加**新架构，不是替换
2. `strategies.py` 的 dict 被 `_get_data_collection_skills()` 直接使用，删除后如果没有新的调用方接入，数据采集路由会断裂
3. 这些 dict 的替换属于 Phase 3（Agent 通用化 + strategies.py 重构），不是本次清理范围

**仅修改 `_get_data_collection_skills` 中 L169-170 的硬编码 xueqiu 添加**：

```python
# 旧代码 (L169-170)
if "xueqiu" not in aspect_skills:
    aspect_skills.append("xueqiu")

# 新代码：从 registry 的 manifest 动态添加 structured_db skills
for name, m in self._skill_registry.all_manifests().items():
    if m.priority == "structured_db" and name not in aspect_skills:
        aspect_skills.append(name)
```

但这需要 `_get_data_collection_skills` 接收 registry 参数，影响面较大。**本次不做**，留到 Phase 3。

### 3.3 `src/core/orchestrator/orchestrator.py` — 切换注册源（中风险）

**3.3.1 删除旧 import + factory 注册**（L280, L289）

```python
# 旧代码
from src.skills.analysis import XueqiuSkill
...
("xueqiu", XueqiuSkill),

# 删除这两行
```

**3.3.2 新增 discovery 初始化**

在 orchestrator 的 skill 初始化区块中，在 `register_core_skills()` 之后调用 `init_from_discovery()`：

```python
# 新增
skill_registry.init_from_discovery(Path("src/skills"))
```

这会让 discovery 发现 xueqiu/SKILL.md 并自动注册 factory。

**3.3.3 更新日志计数**（L292）

```python
# 旧代码
logger.info("Orchestrator: registered 7 professional analysis Skills via factory")

# 新代码（如果仍然保留 analysis skills 的 factory 注册，则 7→8）
# 或者如果完全移交给 discovery，删除此日志
```

### 3.4 `src/skills/registry.py` — 删除 CATEGORY_TO_SKILLS 中 xueqiu（低风险）

**3.4.1** 从 `CATEGORY_TO_SKILLS` 局部变量中删除 `"xueqiu"` 条目（L401, L403, L408）

因为 discovery 的 `build_registries()` 会自动生成 `category_to_skills`，旧映射不再需要 xueqiu 条目。但 `load_skills_for_category()` 目前仍直接使用这个局部 dict，所以删除 xueqiu 条目前需确保 discovery 路径已补位。

**本次仅在 orchestrator 调用 `init_from_discovery()` 后删除**。

### 3.5 `src/skills/skill_keywords.py` — 删除 xueqiu 条目（低风险）

**3.5.1** 删除 `SKILL_KEYWORDS["xueqiu"]`（L132-138）

**3.5.2** 删除 `get_skill_description()` 中的 `"xueqiu"` 条目（L259）

数据来自 `manifest.keywords` 和 `manifest.description`，通过 discovery 自动构建。

### 3.6 `config/keyword_mappings.yaml` — 删除 xueqiu 条目（低风险）

**3.6.1** 删除 `financial.skills` 中的 `- "xueqiu"`（L285）

**3.6.2** 删除整个 `stock_quote` 条目（L287-307）

数据来自 `manifest.data_source_keywords` 和 `manifest.keywords`，通过 discovery 自动构建。

---

## 4. 执行顺序

```
Step 1: orchestrator.py — 新增 init_from_discovery()，保留旧 factory 注册
Step 2: 验证 — 运行测试确认新旧路径共存
Step 3: orchestrator.py — 删除旧 import + factory 注册
Step 4: generic_agent.py — 通用化替换（3.1.1-3.1.4）
Step 5: registry.py — 删除 CATEGORY_TO_SKILLS 中 xueqiu
Step 6: skill_keywords.py — 删除 xueqiu 条目
Step 7: keyword_mappings.yaml — 删除 xueqiu 条目
Step 8: 验证 — 全量单元测试 + 真实数据获取测试
Step 9: 修正日志计数
```

## 5. 回滚方案

每个 Step 独立 commit，回滚时 `git revert` 单步即可。

## 6. 验证标准

| # | 验证项 | 方法 |
|---|--------|------|
| 1 | `registry.get("xueqiu")` 返回 XueqiuSkill 实例 | 单元测试 |
| 2 | `registry.get_manifest("xueqiu")` 返回正确 manifest | 单元测试 |
| 3 | `registry.get_by_capability("quote")` 返回 xueqiu | 单元测试 |
| 4 | `skill.infer_actions("financial", "SH600519")` = `["quote", "kline"]` | 真实数据测试 |
| 5 | `skill.infer_actions("competitive", "SH600519")` = `["quote", "kline", "hot_stocks"]` | 真实数据测试 |
| 6 | `skill.infer_actions("", "AAPL")` = `["search_and_quote"]` | 真实数据测试 |
| 7 | `skill.resolve_identifier("腾讯控股投资价值分析", "估值")` 非空 | 真实数据测试 |
| 8 | A股 quote 真实数据获取成功 | 真实数据测试 |
| 9 | 港股 search_and_quote 真实数据获取成功 | 真实数据测试 |
| 10 | 美股 search_and_quote 真实数据获取成功 | 真实数据测试 |
| 11 | 全量单元测试 0 回归 | pytest |
