# Phase 2: Migrate Inconsistent LLM Call Patterns to `call_llm(routing_hint=...)`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate all 5 inconsistent LLM call patterns by migrating them to `call_llm(routing_hint=...)`, so every LLM call goes through the unified routing infrastructure.

**Architecture:** Each call site is replaced with `call_llm()` + `RoutingHint`. The `RoutingHint.action` field maps to a profile via `LLMProfileRegistry.action_routing`. For sync callers, a new `call_llm_sync()` wrapper bridges async→sync. `LLMSkill` gains `routing_hint` parameter (deprecation path, not deletion).

**Tech Stack:** Python 3.10+, asyncio, dataclasses, pytest, pytest-asyncio

---

## File Structure

### New Files
- `tests/unit/core/test_llm_client_sync.py` — Tests for `call_llm_sync()` wrapper

### Modified Files
- `src/core/llm_client.py` — Add `call_llm_sync()` wrapper
- `src/core/agents/generic_agent.py` — Replace `_call_llm_directly()` with `call_llm(routing_hint=...)`
- `src/core/quality/llm_judge.py` — Replace `_call_llm_sync()` with `call_llm_sync(routing_hint=...)`
- `src/core/quality/layer3_depth.py` — Replace `_call_llm()` with `call_llm_sync(routing_hint=...)`
- `src/core/quality/layer2_methodology.py` — Replace `_call_llm()` with `call_llm_sync(routing_hint=...)`
- `src/skills/llm_skill.py` — Add `routing_hint` parameter to `execute()`
- `src/api/research_api.py` — Replace 3 `LLMSkill()` call sites with `call_llm(routing_hint=...)`
- `src/core/task_structure.py` — Replace `_get_llm_skill()` with `call_llm(routing_hint=...)`
- `src/core/semantic_intent.py` — Replace `_get_llm_skill()` with `call_llm(routing_hint=...)`
- `src/core/intent/revision_intent_analyzer.py` — Replace `LLMSkill()` with `call_llm(routing_hint=...)`
- `src/core/adjustment/atomic_operations/translate_operation.py` — Replace `LLMSkill()` with `call_llm(routing_hint=...)`
- `src/core/quality/findings.py` — Replace `LLMSkill()` with `call_llm_sync(routing_hint=...)` + fix missing `await`
- `src/core/adjustment/batch_revision_service.py` — Replace `LLMSkill()` fallback with `call_llm(routing_hint=...)`
- `src/core/memory/extraction/llm_entity_extractor.py` — Replace duck-typed LLM client with `call_llm(routing_hint=...)`
- `src/core/quality/semantic_scorer.py` — Remove `llm_client` passthrough (no longer needed)
- `src/core/quality/semantic_adapter.py` — Remove `llm_client` passthrough (no longer needed)
- `config/llm_routing.yaml` — Add action_routing entries for all new actions

---

## Task 1: Add `call_llm_sync()` to `src/core/llm_client.py`

Several callers (layer2, layer3, llm_judge, findings) are synchronous but need to use `call_llm()`. We need a sync wrapper.

**Files:**
- Modify: `src/core/llm_client.py`
- Create: `tests/unit/core/test_llm_client_sync.py`

- [ ] **Step 1: Write failing tests for `call_llm_sync()`**

```python
# tests/unit/core/test_llm_client_sync.py

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from src.config.llm_profiles import RoutingHint


class TestCallLlmSync:
    @patch("src.core.llm_client._router", None)
    @patch("src.core.llm_client.settings")
    def test_sync_call_returns_result(self, mock_settings):
        mock_settings.llm.model = "gpt-4o"
        mock_settings.llm.api_key = "sk-test"
        mock_settings.llm.base_url = "https://api.openai.com/v1"
        mock_settings.llm.max_tokens = 2048
        mock_settings.llm.temperature = 0.7
        mock_settings.llm.cheap_model = "gpt-4o-mini"
        mock_settings.llm.top_p = 1.0
        mock_settings.llm.frequency_penalty = 0.0
        mock_settings.llm.presence_penalty = 0.0
        mock_settings.llm.cost_limit_per_report = 0.0

        from src.core.llm_client import call_llm_sync

        with patch("src.core.llm_client.call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {"success": True, "content": "hello", "model": "gpt-4o"}
            result = call_llm_sync(prompt="test", routing_hint=RoutingHint(action="quality_judge"))
            assert result["success"] is True
            assert result["content"] == "hello"
            mock_call.assert_called_once()
            call_kwargs = mock_call.call_args
            assert call_kwargs.kwargs.get("routing_hint") == RoutingHint(action="quality_judge")

    @patch("src.core.llm_client.settings")
    def test_sync_call_without_routing_hint(self, mock_settings):
        mock_settings.llm.model = "gpt-4o"
        mock_settings.llm.api_key = "sk-test"
        mock_settings.llm.base_url = "https://api.openai.com/v1"
        mock_settings.llm.max_tokens = 2048
        mock_settings.llm.temperature = 0.7
        mock_settings.llm.cheap_model = "gpt-4o-mini"
        mock_settings.llm.top_p = 1.0
        mock_settings.llm.frequency_penalty = 0.0
        mock_settings.llm.presence_penalty = 0.0
        mock_settings.llm.cost_limit_per_report = 0.0

        from src.core.llm_client import call_llm_sync

        with patch("src.core.llm_client.call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = {"success": True, "content": "result"}
            result = call_llm_sync(prompt="test")
            assert result["success"] is True

    @patch("src.core.llm_client.settings")
    def test_sync_call_handles_exception(self, mock_settings):
        mock_settings.llm.model = "gpt-4o"
        mock_settings.llm.api_key = "sk-test"
        mock_settings.llm.base_url = "https://api.openai.com/v1"
        mock_settings.llm.max_tokens = 2048
        mock_settings.llm.temperature = 0.7
        mock_settings.llm.cheap_model = "gpt-4o-mini"
        mock_settings.llm.top_p = 1.0
        mock_settings.llm.frequency_penalty = 0.0
        mock_settings.llm.presence_penalty = 0.0
        mock_settings.llm.cost_limit_per_report = 0.0

        from src.core.llm_client import call_llm_sync

        with patch("src.core.llm_client.call_llm", new_callable=AsyncMock) as mock_call:
            mock_call.side_effect = Exception("API error")
            result = call_llm_sync(prompt="test")
            assert result["success"] is False
            assert "API error" in result.get("message", "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/core/test_llm_client_sync.py -v --tb=short 2>&1 | Out-File tmp_test.txt -Encoding utf8`
Expected: FAIL — `ImportError: cannot import name 'call_llm_sync'`

- [ ] **Step 3: Implement `call_llm_sync()` in `src/core/llm_client.py`**

Add this function after `call_llm()` (after line 163):

```python
def call_llm_sync(
    prompt: str,
    model: Optional[str] = None,
    system_prompt: str = "",
    fallback_model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    routing_hint: Optional[RoutingHint] = None,
) -> Dict[str, Any]:
    """Synchronous wrapper for call_llm().

    Handles async event loop bridging automatically:
    - If no event loop is running: uses asyncio.run()
    - If an event loop is already running: runs in a background thread
    """
    import asyncio
    import concurrent.futures

    coro = call_llm(
        prompt=prompt,
        model=model,
        system_prompt=system_prompt,
        fallback_model=fallback_model,
        max_tokens=max_tokens,
        temperature=temperature,
        api_key=api_key,
        base_url=base_url,
        routing_hint=routing_hint,
    )

    try:
        asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result(timeout=120)
    except RuntimeError:
        return asyncio.run(coro)
    except Exception as e:
        return {"success": False, "message": str(e), "error": "sync_call_failed"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/core/test_llm_client_sync.py -v --tb=short 2>&1 | Out-File tmp_test.txt -Encoding utf8`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/llm_client.py tests/unit/core/test_llm_client_sync.py
git commit -m "feat: add call_llm_sync() wrapper for synchronous callers"
```

---

## Task 2: Add `routing_hint` parameter to `LLMSkill.execute()`

**Files:**
- Modify: `src/skills/llm_skill.py`

- [ ] **Step 1: Modify `LLMSkill.execute()` to accept and forward `routing_hint`**

In `src/skills/llm_skill.py`, update the `execute()` method:

Replace:
```python
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute LLM call

        Args:
            prompt: User prompt (required)
            model: Model name (default uses model from config)
            system_prompt: System prompt (optional)
            fallback_model: Fallback model (optional, default uses cheap_model from config)
            max_tokens: Maximum generation tokens (default uses max_tokens from config)
            temperature: Temperature parameter (default uses temperature from config)

        Returns:
            Result dictionary containing content, usage, model
        """
        prompt = kwargs.get("prompt", "")
        
        # Read defaults from configuration system
        model = kwargs.get("model", settings.llm.model)
        system_prompt = kwargs.get("system_prompt", "")
        fallback_model = kwargs.get("fallback_model", settings.llm.cheap_model)
        max_tokens = kwargs.get("max_tokens", settings.llm.max_tokens)
        temperature = kwargs.get("temperature", settings.llm.temperature)

        if not prompt or not prompt.strip():
            return self._failure("prompt cannot be empty")

        # Check cost limit
        if settings.llm.cost_limit_per_report > 0:
            # Simple estimation: assume ~$0.01 per 1000 tokens
            estimated_cost = (max_tokens / 1000) * 0.01
            if estimated_cost > settings.llm.cost_limit_per_report:
                return self._failure(
                    f"Estimated cost ${estimated_cost:.4f} exceeds per-report limit ${settings.llm.cost_limit_per_report:.2f}",
                    "Cost limit triggered"
                )

        # Try primary model first
        try:
            response = await self._call_llm(
                prompt=prompt,
                model=model,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return self._parse_response(response, model)

        except Exception as primary_err:
            # Try fallback model
            if fallback_model and fallback_model != model:
                try:
                    response = await self._call_llm(
                        prompt=prompt,
                        model=fallback_model,
                        system_prompt=system_prompt,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    )
                    result = self._parse_response(response, fallback_model)
                    result["fallback_used"] = True
                    return result
                except Exception as fallback_err:
                    return self._failure(
                        f"Primary: {primary_err}; Fallback: {fallback_err}",
                        "LLM call failed (both primary and fallback unavailable)"
                    )
            return self._failure(str(primary_err), "LLM call failed")
```

With:
```python
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute LLM call

        Args:
            prompt: User prompt (required)
            model: Model name (default uses model from config)
            system_prompt: System prompt (optional)
            fallback_model: Fallback model (optional, default uses cheap_model from config)
            max_tokens: Maximum generation tokens (default uses max_tokens from config)
            temperature: Temperature parameter (default uses temperature from config)
            routing_hint: Routing hint for profile-based routing (optional)

        Returns:
            Result dictionary containing content, usage, model
        """
        prompt = kwargs.get("prompt", "")
        routing_hint = kwargs.get("routing_hint")

        if routing_hint is not None:
            from src.core.llm_client import call_llm
            result = await call_llm(
                prompt=prompt,
                model=kwargs.get("model"),
                system_prompt=kwargs.get("system_prompt", ""),
                fallback_model=kwargs.get("fallback_model"),
                max_tokens=kwargs.get("max_tokens"),
                temperature=kwargs.get("temperature"),
                routing_hint=routing_hint,
            )
            if result.get("success"):
                return self._success(
                    {"content": result["content"], "model": result.get("model", ""), "usage": result.get("usage", {})},
                    "LLM call successful",
                )
            return self._failure(result.get("message", "LLM call failed"), result.get("error", "llm_call_failed"))

        model = kwargs.get("model", settings.llm.model)
        system_prompt = kwargs.get("system_prompt", "")
        fallback_model = kwargs.get("fallback_model", settings.llm.cheap_model)
        max_tokens = kwargs.get("max_tokens", settings.llm.max_tokens)
        temperature = kwargs.get("temperature", settings.llm.temperature)

        if not prompt or not prompt.strip():
            return self._failure("prompt cannot be empty")

        if settings.llm.cost_limit_per_report > 0:
            estimated_cost = (max_tokens / 1000) * 0.01
            if estimated_cost > settings.llm.cost_limit_per_report:
                return self._failure(
                    f"Estimated cost ${estimated_cost:.4f} exceeds per-report limit ${settings.llm.cost_limit_per_report:.2f}",
                    "Cost limit triggered"
                )

        try:
            response = await self._call_llm(
                prompt=prompt,
                model=model,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return self._parse_response(response, model)

        except Exception as primary_err:
            if fallback_model and fallback_model != model:
                try:
                    response = await self._call_llm(
                        prompt=prompt,
                        model=fallback_model,
                        system_prompt=system_prompt,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    )
                    result = self._parse_response(response, fallback_model)
                    result["fallback_used"] = True
                    return result
                except Exception as fallback_err:
                    return self._failure(
                        f"Primary: {primary_err}; Fallback: {fallback_err}",
                        "LLM call failed (both primary and fallback unavailable)"
                    )
            return self._failure(str(primary_err), "LLM call failed")
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `pytest tests/unit/ -v --tb=short 2>&1 | Out-File tmp_test.txt -Encoding utf8`
Expected: ALL PASS (no regressions)

- [ ] **Step 3: Commit**

```bash
git add src/skills/llm_skill.py
git commit -m "feat: add routing_hint parameter to LLMSkill.execute()"
```

---

## Task 3: Migrate `GenericAgent._call_llm_directly()` to `call_llm(routing_hint=...)`

**Files:**
- Modify: `src/core/agents/generic_agent.py`

- [ ] **Step 1: Replace `_call_llm_directly()` body**

In `src/core/agents/generic_agent.py`, replace the `_call_llm_directly` method (lines 4302-4353):

Replace:
```python
    async def _call_llm_directly(
        self,
        prompt: str,
        system_prompt: str = "",
        max_tokens: int = 500,
        temperature: float = 0.7,
    ) -> Dict[str, Any]:
        """
        Agent 直接调用 LLM（独立于 LLMSkill）
        
        用于关键词扩展、决策辅助等 Agent 内部能力。
        不经过 Skill Registry，直接使用 OpenAI API。
        
        Args:
            prompt: 用户提示
            system_prompt: 系统提示（可选）
            max_tokens: 最大输出 token 数
            temperature: 温度参数
            
        Returns:
            {"success": True, "content": "..."} 或 {"success": False, "error": "..."}
        """
        try:
            from openai import AsyncOpenAI
            from src.config import settings
            
            client = AsyncOpenAI(
                api_key=settings.llm.api_key,
                base_url=settings.llm.base_url,
            )
            
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            # 使用便宜模型
            model = getattr(settings.llm, 'cheap_model', None) or settings.llm.model
            
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            
            content = response.choices[0].message.content
            return {"success": True, "content": content}
            
        except Exception as e:
            logger.warning(f"GenericAgent {self.agent_id}: LLM 直接调用失败: {e}")
            return {"success": False, "content": "", "error": str(e)}
```

With:
```python
    async def _call_llm_directly(
        self,
        prompt: str,
        system_prompt: str = "",
        max_tokens: int = 500,
        temperature: float = 0.7,
        action: str = "keyword_expand",
    ) -> Dict[str, Any]:
        """
        Agent 直接调用 LLM（通过统一 call_llm 接口）

        用于关键词扩展、决策辅助等 Agent 内部能力。

        Args:
            prompt: 用户提示
            system_prompt: 系统提示（可选）
            max_tokens: 最大输出 token 数
            temperature: 温度参数
            action: 路由动作标识（默认 "keyword_expand"）

        Returns:
            {"success": True, "content": "..."} 或 {"success": False, "error": "..."}
        """
        try:
            from src.core.llm_client import call_llm
            from src.config.llm_profiles import RoutingHint

            result = await call_llm(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                routing_hint=RoutingHint(agent_type="generic", action=action),
            )
            return result

        except Exception as e:
            logger.warning(f"GenericAgent {self.agent_id}: LLM 直接调用失败: {e}")
            return {"success": False, "content": "", "error": str(e)}
```

- [ ] **Step 2: Verify tests still pass**

Run: `pytest tests/unit/ -v --tb=short 2>&1 | Out-File tmp_test.txt -Encoding utf8`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add src/core/agents/generic_agent.py
git commit -m "refactor: migrate GenericAgent._call_llm_directly() to call_llm(routing_hint=...)"
```

---

## Task 4: Migrate `LLMJudgeChecker._call_llm_sync()` to `call_llm_sync(routing_hint=...)`

**Files:**
- Modify: `src/core/quality/llm_judge.py`

- [ ] **Step 1: Replace `_call_llm_sync()` body**

In `src/core/quality/llm_judge.py`, replace the `_call_llm_sync` method (lines 64-91):

Replace:
```python
    def _call_llm_sync(self, prompt: str) -> str:
        """Synchronous LLM call with async event loop compatibility."""
        from openai import AsyncOpenAI
        from src.config import settings

        async def _call():
            client = AsyncOpenAI(api_key=settings.llm.api_key, base_url=settings.llm.base_url)
            try:
                model = getattr(settings.llm, 'cheap_model', None) or settings.llm.model
                resp = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "You are a strict quality reviewer. Output only JSON."},
                        {"role": "user", "content": prompt}],
                    max_tokens=500, temperature=0.3)
                return resp.choices[0].message.content or ""
            finally:
                try:
                    await client.close()
                except Exception:
                    pass

        try:
            asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, _call()).result(timeout=60)
        except RuntimeError:
            return asyncio.run(_call())
```

With:
```python
    def _call_llm_sync(self, prompt: str) -> str:
        """Synchronous LLM call via unified call_llm_sync."""
        from src.core.llm_client import call_llm_sync
        from src.config.llm_profiles import RoutingHint

        result = call_llm_sync(
            prompt=prompt,
            system_prompt="You are a strict quality reviewer. Output only JSON.",
            max_tokens=500,
            temperature=0.3,
            routing_hint=RoutingHint(action="quality_judge"),
        )
        if result.get("success"):
            return result.get("content", "")
        logger.warning(f"LLM judge call failed: {result.get('message', 'unknown')}")
        return ""
```

Also remove the now-unused `import concurrent.futures` at the top of the file if it's only used by the old `_call_llm_sync`.

- [ ] **Step 2: Verify tests still pass**

Run: `pytest tests/unit/ -v --tb=short 2>&1 | Out-File tmp_test.txt -Encoding utf8`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add src/core/quality/llm_judge.py
git commit -m "refactor: migrate LLMJudgeChecker._call_llm_sync() to call_llm_sync(routing_hint=...)"
```

---

## Task 5: Migrate `Layer3DepthScorer._call_llm()` to `call_llm_sync(routing_hint=...)`

**Files:**
- Modify: `src/core/quality/layer3_depth.py`

- [ ] **Step 1: Replace `_call_llm()` body**

In `src/core/quality/layer3_depth.py`, replace the `_call_llm` method (lines 202-235):

Replace:
```python
    def _call_llm(self, prompt: str) -> str:
        """同步 LLM 调用"""
        from src.config import settings
        from openai import AsyncOpenAI

        async def _do():
            client = AsyncOpenAI(
                api_key=settings.llm.api_key,
                base_url=settings.llm.base_url,
            )
            try:
                model = settings.llm.model
                resp = await client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "你是严格的分析质量评审专家。仅输出JSON。"},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=800,
                    temperature=0.2,
                )
                return resp.choices[0].message.content or ""
            finally:
                try:
                    await client.close()
                except Exception:
                    pass

        try:
            asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, _do()).result(timeout=90)
        except RuntimeError:
            return asyncio.run(_do())
```

With:
```python
    def _call_llm(self, prompt: str) -> str:
        """同步 LLM 调用 — 通过统一 call_llm_sync"""
        from src.core.llm_client import call_llm_sync
        from src.config.llm_profiles import RoutingHint

        result = call_llm_sync(
            prompt=prompt,
            system_prompt="你是严格的分析质量评审专家。仅输出JSON。",
            max_tokens=800,
            temperature=0.2,
            routing_hint=RoutingHint(action="quality_judge"),
        )
        if result.get("success"):
            return result.get("content", "")
        logger.warning(f"Layer3 LLM call failed: {result.get('message', 'unknown')}")
        return ""
```

Also remove the now-unused `import concurrent.futures` at the top of the file if it's only used by the old `_call_llm`.

- [ ] **Step 2: Verify tests still pass**

Run: `pytest tests/unit/ -v --tb=short 2>&1 | Out-File tmp_test.txt -Encoding utf8`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add src/core/quality/layer3_depth.py
git commit -m "refactor: migrate Layer3DepthScorer._call_llm() to call_llm_sync(routing_hint=...)"
```

---

## Task 6: Migrate `Layer2MethodologyScorer._call_llm()` to `call_llm_sync(routing_hint=...)`

**Files:**
- Modify: `src/core/quality/layer2_methodology.py`

- [ ] **Step 1: Replace `_call_llm()` body**

In `src/core/quality/layer2_methodology.py`, replace the `_call_llm` method (lines 209-229):

Replace:
```python
    def _call_llm(self, prompt: str) -> str:
        """同步 LLM 调用"""
        import asyncio

        async def _do():
            if hasattr(self._llm_client, "execute"):
                resp = await self._llm_client.execute(prompt=prompt)
                if isinstance(resp, dict):
                    data = resp.get("data", resp)
                    if isinstance(data, dict):
                        return data.get("content", "")
                    return str(data)
                return str(resp)
            elif callable(self._llm_client):
                return self._llm_client(prompt)
            return ""

        try:
            return asyncio.run(_do())
        except RuntimeError:
            return ""
```

With:
```python
    def _call_llm(self, prompt: str) -> str:
        """同步 LLM 调用 — 通过统一 call_llm_sync"""
        from src.core.llm_client import call_llm_sync
        from src.config.llm_profiles import RoutingHint

        result = call_llm_sync(
            prompt=prompt,
            routing_hint=RoutingHint(action="framework_match"),
        )
        if result.get("success"):
            return result.get("content", "")
        logger.warning(f"Layer2 LLM call failed: {result.get('message', 'unknown')}")
        return ""
```

- [ ] **Step 2: Verify tests still pass**

Run: `pytest tests/unit/ -v --tb=short 2>&1 | Out-File tmp_test.txt -Encoding utf8`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add src/core/quality/layer2_methodology.py
git commit -m "refactor: migrate Layer2MethodologyScorer._call_llm() to call_llm_sync(routing_hint=...)"
```

---

## Task 7: Migrate `research_api.py` LLMSkill call sites to `call_llm(routing_hint=...)`

**Files:**
- Modify: `src/api/research_api.py`

- [ ] **Step 1: Replace 3 LLMSkill call sites**

**Site 1 (lines ~1387-1404):** Replace the LLMSkill framework modify block:

Replace:
```python
        try:
            from src.skills.llm_skill import LLMSkill
            llm_skill = LLMSkill()
        except ImportError:
            import sys, pathlib
            project_root = pathlib.Path(__file__).parent.parent.parent
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))
            from src.skills.llm_skill import LLMSkill
            llm_skill = LLMSkill()
        try:
            from src.config.settings import settings as app_settings
            llm_config = session.get('llm_config', {})
            result = await asyncio.wait_for(
                llm_skill.execute(prompt=prompt, model=llm_config.get('model', app_settings.llm.model), max_tokens=llm_config.get('max_tokens', app_settings.llm.max_tokens)),
                timeout=30)
        except Exception:
            return {'action': 'modify', 'message': "I understand you'd like to adjust the framework. Please tell me what changes you'd like to make.", 'new_sections': None}
```

With:
```python
        try:
            from src.core.llm_client import call_llm
            from src.config.llm_profiles import RoutingHint
            from src.config.settings import settings as app_settings
            llm_config = session.get('llm_config', {})
            result = await asyncio.wait_for(
                call_llm(
                    prompt=prompt,
                    model=llm_config.get('model') or None,
                    max_tokens=llm_config.get('max_tokens') or None,
                    routing_hint=RoutingHint(action="framework_modify"),
                ),
                timeout=30,
            )
        except Exception:
            return {'action': 'modify', 'message': "I understand you'd like to adjust the framework. Please tell me what changes you'd like to make.", 'new_sections': None}
```

Note: The `call_llm` result format is `{"success": True, "content": "..."}` while LLMSkill's was `{"success": True, "data": {"content": "..."}}`. The existing code on the lines after this block already accesses `result.get('success')` and `result.get('content', '')`, so the `call_llm` format is directly compatible.

**Site 2 (lines ~1752-1766):** Replace the LLMSkill section inference block:

Replace:
```python
        try:
            from src.skills.llm_skill import LLMSkill
            llm_skill = LLMSkill()
        except ImportError:
            import sys, pathlib
            project_root = pathlib.Path(__file__).parent.parent.parent
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))
            from src.skills.llm_skill import LLMSkill
            llm_skill = LLMSkill()
        try:
            from src.config.settings import settings as app_settings
            result = await asyncio.wait_for(
                llm_skill.execute(prompt=prompt, model=app_settings.llm.model, max_tokens=app_settings.llm.max_tokens, temperature=0.3),
                timeout=30)
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning(f"Failed to infer framework sections: {e}")
            return []
```

With:
```python
        try:
            from src.core.llm_client import call_llm
            from src.config.llm_profiles import RoutingHint
            result = await asyncio.wait_for(
                call_llm(
                    prompt=prompt,
                    temperature=0.3,
                    routing_hint=RoutingHint(action="section_inference"),
                ),
                timeout=30,
            )
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning(f"Failed to infer framework sections: {e}")
            return []
```

**Site 3 (lines ~2183-2186):** Replace the LLMSkill param extraction block:

Replace:
```python
        try:
            from src.skills.llm_skill import LLMSkill
            llm = LLMSkill()
            result = await llm.execute(prompt=prompt)
            if isinstance(result, dict):
                raw = result.get('content', '')
                if not raw:
                    return default_params
            else:
                raw = str(result)
```

With:
```python
        try:
            from src.core.llm_client import call_llm
            from src.config.llm_profiles import RoutingHint
            result = await call_llm(
                prompt=prompt,
                routing_hint=RoutingHint(action="param_extraction"),
            )
            if isinstance(result, dict) and result.get("success"):
                raw = result.get('content', '')
                if not raw:
                    return default_params
            else:
                raw = ''
```

- [ ] **Step 2: Verify tests still pass**

Run: `pytest tests/unit/ -v --tb=short 2>&1 | Out-File tmp_test.txt -Encoding utf8`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add src/api/research_api.py
git commit -m "refactor: migrate research_api.py LLMSkill call sites to call_llm(routing_hint=...)"
```

---

## Task 8: Migrate `task_structure.py` and `semantic_intent.py` to `call_llm(routing_hint=...)`

**Files:**
- Modify: `src/core/task_structure.py`
- Modify: `src/core/semantic_intent.py`

- [ ] **Step 1: Replace `_analyze_with_llm` in `task_structure.py`**

In `src/core/task_structure.py`, replace the `_analyze_with_llm` method body (lines 363-410):

Replace the LLM call section (lines 391-397):
```python
        # Call LLM
        result = await llm_skill.execute(
            prompt=prompt,
            system_prompt=system_prompt,
            model=self._llm_model,
            max_tokens=2048,
            temperature=0.1,
        )
```

With:
```python
        from src.core.llm_client import call_llm
        from src.config.llm_profiles import RoutingHint

        result = await call_llm(
            prompt=prompt,
            system_prompt=system_prompt,
            model=self._llm_model or None,
            max_tokens=2048,
            temperature=0.1,
            routing_hint=RoutingHint(action="task_structure"),
        )
```

The result format check on line 399 (`result.get("success")`) is the same for both `call_llm` and `LLMSkill.execute()`, so the downstream code is compatible.

Now remove the `_get_llm_skill` method (lines 270-283) since it's no longer needed. Also remove the `self._llm_skill` attribute from `__init__`.

- [ ] **Step 2: Replace `_analyze_with_llm` in `semantic_intent.py`**

In `src/core/semantic_intent.py`, replace the LLM call in `_analyze_with_llm` (lines 282-292):

Replace:
```python
        llm_skill = self._get_llm_skill()
        system_prompt, user_template = self._load_intent_prompts()
        prompt = self._format_intent_prompt(user_template, user_request, requirement)
        result = await llm_skill.execute(prompt=prompt, system_prompt=system_prompt,
                                          model=self._llm_model, max_tokens=self._max_tokens,
                                          temperature=self._temperature)
```

With:
```python
        from src.core.llm_client import call_llm
        from src.config.llm_profiles import RoutingHint

        system_prompt, user_template = self._load_intent_prompts()
        prompt = self._format_intent_prompt(user_template, user_request, requirement)
        result = await call_llm(
            prompt=prompt,
            system_prompt=system_prompt,
            model=self._llm_model or None,
            max_tokens=self._max_tokens or None,
            temperature=self._temperature or None,
            routing_hint=RoutingHint(action="intent_analysis"),
        )
```

The result format from `call_llm` returns `{"success": True, "content": "..."}` while `LLMSkill.execute()` returns `{"success": True, "data": {"content": "..."}}`. The existing code on line 290 accesses `result["content"]` which matches `call_llm`'s format directly. However, line 291 accesses `result.get("model", "")` which exists in `call_llm`'s response.

Now remove the `_get_llm_skill` method (lines 210-219) since it's no longer needed. Also remove the `self._llm_skill` attribute from `__init__`.

- [ ] **Step 3: Verify tests still pass**

Run: `pytest tests/unit/ -v --tb=short 2>&1 | Out-File tmp_test.txt -Encoding utf8`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add src/core/task_structure.py src/core/semantic_intent.py
git commit -m "refactor: migrate task_structure and semantic_intent to call_llm(routing_hint=...)"
```

---

## Task 9: Migrate remaining LLMSkill consumers

**Files:**
- Modify: `src/core/intent/revision_intent_analyzer.py`
- Modify: `src/core/adjustment/atomic_operations/translate_operation.py`
- Modify: `src/core/quality/findings.py`
- Modify: `src/core/adjustment/batch_revision_service.py`
- Modify: `src/core/memory/extraction/llm_entity_extractor.py`

- [ ] **Step 1: Migrate `revision_intent_analyzer.py`**

In `src/core/intent/revision_intent_analyzer.py`, replace the `_call_llm` method (lines 251-283):

Replace:
```python
    async def _call_llm(self, user_message: str, report: object) -> str:
        try:
            from src.skills.llm_skill import LLMSkill
            from src.config.settings import settings as app_settings
            llm_skill = LLMSkill()

            system_prompt = _REVISION_SYSTEM_PROMPT.format(
                output_schema=json.dumps(REVISION_JSON_SCHEMA, ensure_ascii=False, indent=2)
            )
            section_context = self._build_section_context(report)
            user_prompt = _REVISION_USER_PROMPT_TEMPLATE.format(
                user_message=user_message,
                section_context=section_context,
            )

            result = await llm_skill.execute(
                prompt=user_prompt,
                system_prompt=system_prompt,
                model=app_settings.llm.cheap_model,
                max_tokens=2048,
                temperature=0.3,
            )
            if not result.get("success"):
                logger.warning(f"LLM intent analysis failed: {result.get('error', 'unknown')}")
                return "{}"
            content = result.get("content", "")
            if not content or not content.strip():
                return "{}"

            json_match = regex_module.search(r'\{.*\}', content, regex_module.DOTALL)
            if json_match:
                return json_match.group(0)
            return content.strip()
        except Exception as e:
```

With:
```python
    async def _call_llm(self, user_message: str, report: object) -> str:
        try:
            from src.core.llm_client import call_llm
            from src.config.llm_profiles import RoutingHint

            system_prompt = _REVISION_SYSTEM_PROMPT.format(
                output_schema=json.dumps(REVISION_JSON_SCHEMA, ensure_ascii=False, indent=2)
            )
            section_context = self._build_section_context(report)
            user_prompt = _REVISION_USER_PROMPT_TEMPLATE.format(
                user_message=user_message,
                section_context=section_context,
            )

            result = await call_llm(
                prompt=user_prompt,
                system_prompt=system_prompt,
                max_tokens=2048,
                temperature=0.3,
                routing_hint=RoutingHint(action="revision_intent"),
            )
            if not result.get("success"):
                logger.warning(f"LLM intent analysis failed: {result.get('error', 'unknown')}")
                return "{}"
            content = result.get("content", "")
            if not content or not content.strip():
                return "{}"

            json_match = regex_module.search(r'\{.*\}', content, regex_module.DOTALL)
            if json_match:
                return json_match.group(0)
            return content.strip()
        except Exception as e:
```

- [ ] **Step 2: Migrate `translate_operation.py`**

In `src/core/adjustment/atomic_operations/translate_operation.py`, replace `_llm_translate_batch` (lines 49-79):

Replace:
```python
    async def _llm_translate_batch(
        self, texts: list[str], target_lang: str
    ) -> list[str]:
        from src.skills.llm_skill import LLMSkill
        from src.config.settings import settings as app_settings

        llm = LLMSkill()
        combined = "\n\n---SEPARATOR---\n\n".join(texts)
        prompt = (
            f"Translate the following text to {target_lang}. "
            f"Preserve all Markdown formatting, table structures, and "
            f"the SEPARATOR markers between sections.\n\n{combined}"
        )
        result = await llm.execute(
            prompt=prompt,
            system_prompt="You are a professional translator.",
            model=app_settings.llm.cheap_model,
            max_tokens=8192,
            temperature=0.3,
        )
        if not result.get("success"):
            raise RuntimeError(f"Translation failed: {result.get('error')}")

        translated = result.get("content", "")
        parts = translated.split("---SEPARATOR---")
        result_texts = []
        for original, part in zip(texts, parts):
            result_texts.append(part.strip() if part.strip() else original)
        while len(result_texts) < len(texts):
            result_texts.append(texts[len(result_texts)])
        return result_texts
```

With:
```python
    async def _llm_translate_batch(
        self, texts: list[str], target_lang: str
    ) -> list[str]:
        from src.core.llm_client import call_llm
        from src.config.llm_profiles import RoutingHint

        combined = "\n\n---SEPARATOR---\n\n".join(texts)
        prompt = (
            f"Translate the following text to {target_lang}. "
            f"Preserve all Markdown formatting, table structures, and "
            f"the SEPARATOR markers between sections.\n\n{combined}"
        )
        result = await call_llm(
            prompt=prompt,
            system_prompt="You are a professional translator.",
            max_tokens=8192,
            temperature=0.3,
            routing_hint=RoutingHint(action="translation"),
        )
        if not result.get("success"):
            raise RuntimeError(f"Translation failed: {result.get('error')}")

        translated = result.get("content", "")
        parts = translated.split("---SEPARATOR---")
        result_texts = []
        for original, part in zip(texts, parts):
            result_texts.append(part.strip() if part.strip() else original)
        while len(result_texts) < len(texts):
            result_texts.append(texts[len(result_texts)])
        return result_texts
```

- [ ] **Step 3: Migrate `findings.py` (also fix missing `await` bug)**

In `src/core/quality/findings.py`, replace `_extract_claims_via_llm` (lines 159-188):

Replace:
```python
def _extract_claims_via_llm(text: str) -> Optional[List[str]]:
    """LLM 通道：抽取核心判断（需要 llm_skill 可用）"""
    try:
        from src.skills.llm_skill import LLMSkill
    except ImportError:
        logger.warning("LLMSkill not available, skipping LLM extraction")
        return None

    prompt = (
        "从以下研究文本中提取 1-3 条核心判断语句。\n"
        "核心判断是作者做出的关键性结论或预测，而不是事实性陈述。\n"
        "每条判断用一句话概括，不超过 80 字。\n"
        "以 JSON 数组格式输出，例如：[\"判断1\", \"判断2\"]\n\n"
        "文本：\n" + text[:3000]
    )

    skill = LLMSkill()
    result = skill.execute(prompt=prompt)
    if not result.get("success"):
        return None

    content = result.get("content", "")
    import json
    try:
        parsed = json.loads(content)
        if isinstance(parsed, list):
            return [str(c).strip() for c in parsed if c]
    except json.JSONDecodeError:
        pass
    return None
```

With:
```python
def _extract_claims_via_llm(text: str) -> Optional[List[str]]:
    """LLM 通道：抽取核心判断 — 通过统一 call_llm_sync"""
    try:
        from src.core.llm_client import call_llm_sync
        from src.config.llm_profiles import RoutingHint
    except ImportError:
        logger.warning("call_llm_sync not available, skipping LLM extraction")
        return None

    prompt = (
        "从以下研究文本中提取 1-3 条核心判断语句。\n"
        "核心判断是作者做出的关键性结论或预测，而不是事实性陈述。\n"
        "每条判断用一句话概括，不超过 80 字。\n"
        "以 JSON 数组格式输出，例如：[\"判断1\", \"判断2\"]\n\n"
        "文本：\n" + text[:3000]
    )

    result = call_llm_sync(
        prompt=prompt,
        routing_hint=RoutingHint(action="claim_extraction"),
    )
    if not result.get("success"):
        return None

    content = result.get("content", "")
    import json
    try:
        parsed = json.loads(content)
        if isinstance(parsed, list):
            return [str(c).strip() for c in parsed if c]
    except json.JSONDecodeError:
        pass
    return None
```

This also fixes the bug where `skill.execute(prompt=prompt)` was called without `await`.

- [ ] **Step 4: Migrate `batch_revision_service.py`**

In `src/core/adjustment/batch_revision_service.py`, replace the constructor's LLMSkill fallback (lines 109-112):

Replace:
```python
        # 延迟导入 LLM Skill
        if self._llm_client is None:
            from src.skills.llm_skill import LLMSkill
            self._llm_client = LLMSkill()
```

With:
```python
        if self._llm_client is None:
            self._llm_client = None
```

And replace `_llm_revise_batch` (lines 384-407) to use `call_llm` directly:

Replace:
```python
    async def _llm_revise_batch(self, prompt: str) -> Optional[str]:
        """调用 LLM 进行批量修订"""
        if self._llm_client is None:
            logger.error("[BatchRevision] LLM client not initialized")
            return None
        
        try:
            # 使用 asyncio.wait_for 添加超时保护
            result = await asyncio.wait_for(
                self._llm_client.execute(prompt=prompt),
                timeout=self._timeout
            )
            # LLMSkill 返回 {"success": True, "content": "...", ...}
            if result and result.get("success"):
                return result.get("content")
            else:
                logger.error(f"[BatchRevision] LLM call failed: {result.get('error', 'Unknown error') if result else 'No result'}")
                return None
        except asyncio.TimeoutError:
            logger.error(f"[BatchRevision] LLM call timed out after {self._timeout}s")
            raise
        except Exception as e:
            logger.error(f"[BatchRevision] LLM call failed: {e}")
            return None
```

With:
```python
    async def _llm_revise_batch(self, prompt: str) -> Optional[str]:
        """调用 LLM 进行批量修订"""
        try:
            from src.core.llm_client import call_llm
            from src.config.llm_profiles import RoutingHint

            result = await asyncio.wait_for(
                call_llm(
                    prompt=prompt,
                    routing_hint=RoutingHint(action="batch_revision"),
                ),
                timeout=self._timeout,
            )
            if result and result.get("success"):
                return result.get("content")
            else:
                logger.error(f"[BatchRevision] LLM call failed: {result.get('error', 'Unknown error') if result else 'No result'}")
                return None
        except asyncio.TimeoutError:
            logger.error(f"[BatchRevision] LLM call timed out after {self._timeout}s")
            raise
        except Exception as e:
            logger.error(f"[BatchRevision] LLM call failed: {e}")
            return None
```

Note: If `self._llm_client` is still injected by some callers (DI pattern), keep the constructor parameter but don't auto-create LLMSkill. The `_llm_revise_batch` now always uses `call_llm` directly, ignoring `self._llm_client`.

- [ ] **Step 5: Migrate `llm_entity_extractor.py`**

In `src/core/memory/extraction/llm_entity_extractor.py`, replace the LLM call methods.

Replace `_extract_via_llm_sync` (lines 122-154):

```python
    def _extract_via_llm_sync(
        self,
        text: str,
        source: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """同步 LLM 提取 — 通过统一 call_llm_sync"""
        try:
            from src.core.llm_client import call_llm_sync
            from src.config.llm_profiles import RoutingHint

            truncated = text[: self._max_llm_chars]
            prompt = _LLM_EXTRACT_PROMPT.format(text=truncated)

            result = call_llm_sync(
                prompt=prompt,
                routing_hint=RoutingHint(action="entity_extraction"),
            )
            return self._parse_llm_response(result)

        except Exception as e:
            logger.warning(f"LLM entity extraction failed (sync): {e}")
            return []
```

Replace `_extract_via_llm` (lines 156-177):

```python
    async def _extract_via_llm(
        self,
        text: str,
        source: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """异步 LLM 提取 — 通过统一 call_llm"""
        try:
            from src.core.llm_client import call_llm
            from src.config.llm_profiles import RoutingHint

            truncated = text[: self._max_llm_chars]
            prompt = _LLM_EXTRACT_PROMPT.format(text=truncated)

            result = await call_llm(
                prompt=prompt,
                routing_hint=RoutingHint(action="entity_extraction"),
            )
            return self._parse_llm_response(result)

        except Exception as e:
            logger.warning(f"LLM entity extraction failed (async): {e}")
            return []
```

The `_parse_llm_response` method currently handles both `LLMSkill` dict format (`{"data": {"content": "..."}}`) and `call_llm` dict format (`{"content": "..."}`). The `_extract_content` method on lines 189-202 already handles both formats because it checks `response.get("data", response)` which falls through to `response.get("content")` when `"data"` key doesn't exist. So `_parse_llm_response` is compatible without changes.

- [ ] **Step 6: Verify tests still pass**

Run: `pytest tests/unit/ -v --tb=short 2>&1 | Out-File tmp_test.txt -Encoding utf8`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/core/intent/revision_intent_analyzer.py src/core/adjustment/atomic_operations/translate_operation.py src/core/quality/findings.py src/core/adjustment/batch_revision_service.py src/core/memory/extraction/llm_entity_extractor.py
git commit -m "refactor: migrate remaining LLMSkill consumers to call_llm(routing_hint=...)"
```

---

## Task 10: Update `config/llm_routing.yaml` with all action routing entries

**Files:**
- Modify: `config/llm_routing.yaml`

- [ ] **Step 1: Add all new action_routing entries**

Read the current `config/llm_routing.yaml` and add these action_routing entries (keeping existing ones):

```yaml
action_routing:
  # Existing
  analyze: strong
  quality_check: strong

  # Quality assessment
  quality_judge: strong
  framework_match: fast
  claim_extraction: fast

  # Agent internal
  keyword_expand: fast
  decision_assist: fast
  task_structure: strong
  intent_analysis: strong
  revision_intent: fast

  # API actions
  framework_modify: fast
  section_inference: fast
  param_extraction: fast

  # Content operations
  translation: fast
  batch_revision: strong
  entity_extraction: fast
```

- [ ] **Step 2: Commit**

```bash
git add config/llm_routing.yaml
git commit -m "feat: add action routing entries for all migrated call sites"
```

---

## Task 11: Clean up unused `llm_client` DI parameters

**Files:**
- Modify: `src/core/quality/semantic_scorer.py`
- Modify: `src/core/quality/semantic_adapter.py`
- Modify: `src/core/quality/layer3_depth.py`
- Modify: `src/core/quality/layer2_methodology.py`
- Modify: `src/core/memory/extraction/llm_entity_extractor.py`

Now that all LLM calls go through `call_llm(routing_hint=...)`, the `llm_client` DI parameter is no longer needed for routing. However, these classes are part of the public API and removing the parameter could break external callers. We keep the parameter but mark it as deprecated.

- [ ] **Step 1: Add deprecation warning to `llm_client` parameters**

In `src/core/quality/layer3_depth.py`, add a deprecation warning in `__init__`:

After line 87 (`self._llm_client = llm_client`), add:
```python
        if llm_client is not None:
            import warnings
            warnings.warn(
                "llm_client parameter is deprecated; LLM calls now use call_llm_sync(routing_hint=...). "
                "The llm_client parameter will be removed in a future version.",
                DeprecationWarning,
                stacklevel=2,
            )
```

Do the same for `src/core/quality/layer2_methodology.py` after line 71 (`self._llm_client = llm_client`).

Do the same for `src/core/memory/extraction/llm_entity_extractor.py` after line 71 (`self._llm_client = llm_client`).

Do the same for `src/core/quality/semantic_scorer.py` after line 68 (`self._llm_client = llm_client`).

Do the same for `src/core/quality/semantic_adapter.py` after line 92 (`self._scorer = SemanticQualityScorer(llm_client=llm_client)`).

- [ ] **Step 2: Verify tests still pass**

Run: `pytest tests/unit/ -v --tb=short 2>&1 | Out-File tmp_test.txt -Encoding utf8`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add src/core/quality/semantic_scorer.py src/core/quality/semantic_adapter.py src/core/quality/layer3_depth.py src/core/quality/layer2_methodology.py src/core/memory/extraction/llm_entity_extractor.py
git commit -m "chore: add deprecation warnings for llm_client DI parameter"
```

---

## Task 12: Final verification — full test suite + grep audit

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/unit/ -v --tb=short 2>&1 | Out-File tmp_test.txt -Encoding utf8`
Expected: ALL PASS, 0 failures

- [ ] **Step 2: Grep audit — verify no remaining raw AsyncOpenAI calls in src/ (excluding llm_client.py, llm_client_pool.py, llm_skill.py)**

Run: `rg "AsyncOpenAI" src/ --glob "!llm_client.py" --glob "!llm_client_pool.py" --glob "!llm_skill.py" -l`

Expected: No results (all raw `AsyncOpenAI` calls should be eliminated from business logic)

- [ ] **Step 3: Grep audit — verify no remaining direct LLMSkill() instantiation in src/ (excluding llm_skill.py itself and registry.py)**

Run: `rg "LLMSkill\(\)" src/ --glob "!llm_skill.py" --glob "!registry.py" -l`

Expected: No results (all direct `LLMSkill()` instantiation should be eliminated)

- [ ] **Step 4: Commit final state if any cleanup needed**

```bash
git add -A
git commit -m "chore: Phase 2 complete — all LLM call patterns migrated to call_llm(routing_hint=...)"
```
