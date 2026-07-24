# Multi-LLM Profile & Intelligent Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a multi-LLM profile registry with intelligent routing, so different agents/actions can use different LLM models with automatic fallback chains.

**Architecture:** New `LLMProfile` dataclass replaces single `LLMConfig`; `LLMRouter` resolves routing hints to profiles; `LLMClientPool` caches `AsyncOpenAI` instances per profile; `call_llm()` gains optional `routing_hint` parameter (backward compat preserved when hint is None).

**Tech Stack:** Python 3.10+, dataclasses, AsyncOpenAI, pytest, pytest-asyncio, FastAPI, Zustand (TypeScript frontend)

---

## File Structure

### New Files (Backend)
- `src/config/llm_profiles.py` — `LLMProfile`, `LLMProfileRegistry`, `RoutingHint` dataclasses
- `src/core/llm_router.py` — `LLMRouter` class (5-level routing resolution)
- `src/core/llm_client_pool.py` — `LLMClientPool` class (cached AsyncOpenAI instances)
- `config/llm_profiles.yaml` — Default profile definitions
- `config/llm_routing.yaml` — Default routing rules
- `tests/unit/config/test_llm_profiles.py` — Tests for LLMProfile/Registry/RoutingHint
- `tests/unit/core/test_llm_router.py` — Tests for LLMRouter
- `tests/unit/core/test_llm_client_pool.py` — Tests for LLMClientPool

### Modified Files (Backend)
- `src/core/llm_client.py` — Add `routing_hint` param to `call_llm`, `call_llm_stream`, `call_llm_vision`
- `src/config/settings.py` — Add `LLMProfileRegistry`, profile CRUD methods, disk persistence, migration
- `src/api/main.py` — Add profile/routing API endpoints, add `init_llm_infrastructure()` to startup
- `tests/unit/config/conftest.py` — Update `reset_settings` to also clean `data/llm_profiles.json`
- `tests/unit/config/test_settings.py` — Add profile CRUD tests
- `tests/unit/core/test_llm_client.py` — Add routing hint tests

### Modified Files (Frontend — Phase 3, separate plan)
- `web/src/types/settings.ts`, `web/src/store/useSettingsStore.ts`, `web/src/components/settings/LLMConfigPanel.tsx`, `web/src/lib/api.ts`, `web/src/components/chat/ChatInput.tsx`

---

## Task 1: LLMProfile, LLMProfileRegistry, RoutingHint Dataclasses

**Files:**
- Create: `src/config/llm_profiles.py`
- Create: `tests/unit/config/test_llm_profiles.py`

- [ ] **Step 1: Write failing tests for LLMProfile defaults**

```python
# tests/unit/config/test_llm_profiles.py

import pytest
from src.config.llm_profiles import LLMProfile, LLMProfileRegistry, RoutingHint


class TestLLMProfile:
    def test_default_values(self):
        profile = LLMProfile(name="test")
        assert profile.name == "test"
        assert profile.display_name == ""
        assert profile.provider == "openai"
        assert profile.api_key == ""
        assert profile.base_url == "https://api.openai.com/v1"
        assert profile.model == "gpt-4o"
        assert profile.temperature == 0.7
        assert profile.max_tokens == 4096
        assert profile.top_p == 1.0
        assert profile.frequency_penalty == 0.0
        assert profile.presence_penalty == 0.0
        assert profile.max_context_tokens == 128000
        assert profile.cost_limit_per_call == 0.0
        assert profile.is_default is False
        assert profile.enabled is True
        assert profile.created_at == ""
        assert profile.updated_at == ""

    def test_custom_values(self):
        profile = LLMProfile(
            name="strong",
            display_name="GPT-4o Strong",
            provider="openai",
            api_key="sk-xxx",
            base_url="https://api.openai.com/v1",
            model="gpt-4o",
            temperature=0.3,
            max_tokens=8000,
            top_p=1.0,
            frequency_penalty=0.0,
            presence_penalty=0.0,
            max_context_tokens=128000,
            cost_limit_per_call=0.5,
            is_default=False,
            enabled=True,
        )
        assert profile.name == "strong"
        assert profile.display_name == "GPT-4o Strong"
        assert profile.temperature == 0.3
        assert profile.max_tokens == 8000
        assert profile.cost_limit_per_call == 0.5


class TestLLMProfileRegistry:
    def test_default_values(self):
        registry = LLMProfileRegistry()
        assert registry.profiles == {}
        assert registry.default_profile == "fast"
        assert registry.fallback_chain == ["strong", "fast", "local"]
        assert registry.fixed_agent_routing == {}
        assert registry.action_routing == {}

    def test_with_profiles(self):
        strong = LLMProfile(name="strong", model="gpt-4o")
        fast = LLMProfile(name="fast", model="deepseek-v4-flash", is_default=True)
        registry = LLMProfileRegistry(
            profiles={"strong": strong, "fast": fast},
            default_profile="fast",
            fallback_chain=["strong", "fast"],
        )
        assert len(registry.profiles) == 2
        assert registry.profiles["strong"].model == "gpt-4o"
        assert registry.default_profile == "fast"


class TestRoutingHint:
    def test_default_values(self):
        hint = RoutingHint()
        assert hint.agent_type is None
        assert hint.action is None
        assert hint.profile_name is None
        assert hint.force_profile is False

    def test_custom_values(self):
        hint = RoutingHint(agent_type="quality_check", action="analyze")
        assert hint.agent_type == "quality_check"
        assert hint.action == "analyze"

    def test_explicit_override(self):
        hint = RoutingHint(profile_name="strong", force_profile=True)
        assert hint.profile_name == "strong"
        assert hint.force_profile is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/config/test_llm_profiles.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.config.llm_profiles'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/config/llm_profiles.py

from dataclasses import dataclass, field
from typing import Optional, Dict, List


@dataclass
class LLMProfile:
    name: str
    display_name: str = ""
    provider: str = "openai"
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    max_context_tokens: int = 128000
    cost_limit_per_call: float = 0.0
    is_default: bool = False
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""


@dataclass
class LLMProfileRegistry:
    profiles: Dict[str, LLMProfile] = field(default_factory=dict)
    default_profile: str = "fast"
    fallback_chain: List[str] = field(default_factory=lambda: ["strong", "fast", "local"])
    fixed_agent_routing: Dict[str, str] = field(default_factory=dict)
    action_routing: Dict[str, str] = field(default_factory=dict)


@dataclass
class RoutingHint:
    agent_type: Optional[str] = None
    action: Optional[str] = None
    profile_name: Optional[str] = None
    force_profile: bool = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/config/test_llm_profiles.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/config/llm_profiles.py tests/unit/config/test_llm_profiles.py
git commit -m "feat: add LLMProfile, LLMProfileRegistry, RoutingHint dataclasses"
```

---

## Task 2: LLMRouter

**Files:**
- Create: `src/core/llm_router.py`
- Create: `tests/unit/core/test_llm_router.py`

- [ ] **Step 1: Write failing tests for LLMRouter**

```python
# tests/unit/core/test_llm_router.py

import pytest
from src.config.llm_profiles import LLMProfile, LLMProfileRegistry, RoutingHint
from src.core.llm_router import LLMRouter


def _make_registry():
    strong = LLMProfile(name="strong", model="gpt-4o", enabled=True)
    fast = LLMProfile(name="fast", model="deepseek-v4-flash", is_default=True, enabled=True)
    local = LLMProfile(name="local", model="qwen2.5", enabled=False)
    vision = LLMProfile(name="vision", model="gpt-4o-vision", enabled=True)
    return LLMProfileRegistry(
        profiles={"strong": strong, "fast": fast, "local": local, "vision": vision},
        default_profile="fast",
        fallback_chain=["strong", "fast", "local"],
        fixed_agent_routing={"quality_check": "strong", "data_collection": "fast"},
        action_routing={"analyze": "strong", "search": "fast", "vision": "vision"},
    )


class TestLLMRouterExplicitOverride:
    def test_explicit_profile_name_returns_that_profile(self):
        router = LLMRouter(_make_registry())
        hint = RoutingHint(profile_name="strong")
        result = router.resolve(hint)
        assert result.name == "strong"

    def test_force_profile_uses_disabled_profile(self):
        router = LLMRouter(_make_registry())
        hint = RoutingHint(profile_name="local", force_profile=True)
        result = router.resolve(hint)
        assert result.name == "local"

    def test_non_force_skips_disabled_profile(self):
        router = LLMRouter(_make_registry())
        hint = RoutingHint(profile_name="local")
        result = router.resolve(hint)
        assert result.name == "fast"  # falls through to default

    def test_nonexistent_profile_falls_to_default(self):
        router = LLMRouter(_make_registry())
        hint = RoutingHint(profile_name="nonexistent")
        result = router.resolve(hint)
        assert result.name == "fast"


class TestLLMRouterFixedAgentMapping:
    def test_known_agent_type_returns_mapped_profile(self):
        router = LLMRouter(_make_registry())
        hint = RoutingHint(agent_type="quality_check")
        result = router.resolve(hint)
        assert result.name == "strong"

    def test_unknown_agent_type_falls_to_default(self):
        router = LLMRouter(_make_registry())
        hint = RoutingHint(agent_type="unknown_agent")
        result = router.resolve(hint)
        assert result.name == "fast"


class TestLLMRouterActionMapping:
    def test_known_action_returns_mapped_profile(self):
        router = LLMRouter(_make_registry())
        hint = RoutingHint(action="analyze")
        result = router.resolve(hint)
        assert result.name == "strong"

    def test_known_fast_action_returns_fast_profile(self):
        router = LLMRouter(_make_registry())
        hint = RoutingHint(action="search")
        result = router.resolve(hint)
        assert result.name == "fast"

    def test_vision_action_returns_vision_profile(self):
        router = LLMRouter(_make_registry())
        hint = RoutingHint(action="vision")
        result = router.resolve(hint)
        assert result.name == "vision"


class TestLLMRouterKeywordAutoClassification:
    def test_reasoning_keyword_maps_to_strong(self):
        router = LLMRouter(_make_registry())
        hint = RoutingHint(action="generate_report")
        result = router.resolve(hint)
        assert result.name == "strong"

    def test_utility_keyword_maps_to_fast(self):
        router = LLMRouter(_make_registry())
        hint = RoutingHint(action="extract_data")
        result = router.resolve(hint)
        assert result.name == "fast"

    def test_unknown_action_no_keyword_match_falls_to_default(self):
        router = LLMRouter(_make_registry())
        hint = RoutingHint(action="custom_thing")
        result = router.resolve(hint)
        assert result.name == "fast"


class TestLLMRouterDefaultFallback:
    def test_empty_hint_returns_default_profile(self):
        router = LLMRouter(_make_registry())
        hint = RoutingHint()
        result = router.resolve(hint)
        assert result.name == "fast"

    def test_no_enabled_profiles_raises_error(self):
        empty_registry = LLMProfileRegistry(
            profiles={
                "strong": LLMProfile(name="strong", enabled=False),
                "fast": LLMProfile(name="fast", enabled=False),
            },
            default_profile="fast",
        )
        router = LLMRouter(empty_registry)
        hint = RoutingHint()
        with pytest.raises(RuntimeError, match="No enabled LLM profile available"):
            router.resolve(hint)

    def test_default_disabled_falls_to_any_enabled(self):
        registry = LLMProfileRegistry(
            profiles={
                "fast": LLMProfile(name="fast", is_default=True, enabled=False),
                "strong": LLMProfile(name="strong", enabled=True),
            },
            default_profile="fast",
        )
        router = LLMRouter(registry)
        hint = RoutingHint()
        result = router.resolve(hint)
        assert result.name == "strong"  # any enabled profile


class TestLLMRouterPriorityOrder:
    def test_explicit_override_takes_priority_over_agent_mapping(self):
        router = LLMRouter(_make_registry())
        hint = RoutingHint(agent_type="quality_check", profile_name="fast")
        result = router.resolve(hint)
        assert result.name == "fast"  # explicit override wins

    def test_agent_mapping_takes_priority_over_action_mapping(self):
        registry = _make_registry()
        registry.fixed_agent_routing["quality_check"] = "strong"
        registry.action_routing["quality_check"] = "fast"
        router = LLMRouter(registry)
        hint = RoutingHint(agent_type="quality_check", action="quality_check")
        result = router.resolve(hint)
        assert result.name == "strong"  # agent mapping wins over action mapping
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/core/test_llm_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.core.llm_router'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/core/llm_router.py

from src.config.llm_profiles import LLMProfile, LLMProfileRegistry, RoutingHint


class LLMRouter:
    REASONING_KEYWORDS = {
        "analyze", "analysis", "generate", "write", "review", "plan",
        "synthesize", "reason", "evaluate", "assess", "judge", "critique",
        "summarize", "interpret", "recommend", "decide", "compare",
    }
    UTILITY_KEYWORDS = {
        "search", "scrape", "format", "translate", "extract", "parse",
        "classify", "count", "lookup", "fetch", "validate", "check",
        "embed", "tokenize", "convert",
    }

    def __init__(self, registry: LLMProfileRegistry):
        self.registry = registry

    def resolve(self, hint: RoutingHint) -> LLMProfile:
        if hint.profile_name:
            profile = self.registry.profiles.get(hint.profile_name)
            if profile and (hint.force_profile or profile.enabled):
                return profile

        if hint.agent_type:
            profile_name = self.registry.fixed_agent_routing.get(hint.agent_type)
            if profile_name:
                profile = self.registry.profiles.get(profile_name)
                if profile and profile.enabled:
                    return profile

        if hint.action:
            profile_name = self.registry.action_routing.get(hint.action)
            if profile_name:
                profile = self.registry.profiles.get(profile_name)
                if profile and profile.enabled:
                    return profile

        if hint.action:
            action_lower = hint.action.lower()
            if any(kw in action_lower for kw in self.REASONING_KEYWORDS):
                for name in ["strong", "default"]:
                    profile = self.registry.profiles.get(name)
                    if profile and profile.enabled:
                        return profile
            elif any(kw in action_lower for kw in self.UTILITY_KEYWORDS):
                for name in ["fast", "default"]:
                    profile = self.registry.profiles.get(name)
                    if profile and profile.enabled:
                        return profile

        default = self.registry.profiles.get(self.registry.default_profile)
        if default and default.enabled:
            return default

        for profile in self.registry.profiles.values():
            if profile.enabled:
                return profile

        raise RuntimeError("No enabled LLM profile available")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/core/test_llm_router.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/llm_router.py tests/unit/core/test_llm_router.py
git commit -m "feat: add LLMRouter with 5-level routing resolution"
```

---

## Task 3: LLMClientPool

**Files:**
- Create: `src/core/llm_client_pool.py`
- Create: `tests/unit/core/test_llm_client_pool.py`

- [ ] **Step 1: Write failing tests for LLMClientPool**

```python
# tests/unit/core/test_llm_client_pool.py

import pytest
from unittest.mock import patch, MagicMock
from src.config.llm_profiles import LLMProfile
from src.core.llm_client_pool import LLMClientPool


def _mock_profile(name="test", api_key="sk-test", base_url="https://test.api.com/v1"):
    return LLMProfile(name=name, api_key=api_key, base_url=base_url)


class TestLLMClientPoolGetClient:
    @pytest.mark.asyncio
    async def test_get_client_creates_asyncopenai(self):
        pool = LLMClientPool()
        profile = _mock_profile()
        with patch("src.core.llm_client_pool.AsyncOpenAI") as mock_openai:
            mock_instance = MagicMock()
            mock_openai.return_value = mock_instance
            client = await pool.get_client(profile)
            mock_openai.assert_called_once_with(api_key="sk-test", base_url="https://test.api.com/v1")
            assert client == mock_instance

    @pytest.mark.asyncio
    async def test_get_client_returns_cached_instance(self):
        pool = LLMClientPool()
        profile = _mock_profile()
        with patch("src.core.llm_client_pool.AsyncOpenAI") as mock_openai:
            mock_instance = MagicMock()
            mock_openai.return_value = mock_instance
            c1 = await pool.get_client(profile)
            c2 = await pool.get_client(profile)
            assert mock_openai.call_count == 1
            assert c1 is c2

    @pytest.mark.asyncio
    async def test_different_profiles_get_different_clients(self):
        pool = LLMClientPool()
        p1 = _mock_profile(name="strong")
        p2 = _mock_profile(name="fast")
        with patch("src.core.llm_client_pool.AsyncOpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            c1 = await pool.get_client(p1)
            c2 = await pool.get_client(p2)
            assert c1 is not c2
            assert mock_openai.call_count == 2


class TestLLMClientPoolInvalidate:
    @pytest.mark.asyncio
    async def test_invalidate_removes_cached_client(self):
        pool = LLMClientPool()
        profile = _mock_profile()
        with patch("src.core.llm_client_pool.AsyncOpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            await pool.get_client(profile)
            assert "test" in pool._clients
            pool.invalidate("test")
            assert "test" not in pool._clients
            await pool.get_client(profile)
            assert mock_openai.call_count == 2

    def test_invalidate_all_clears_cache(self):
        pool = LLMClientPool()
        pool._clients["strong"] = MagicMock()
        pool._clients["fast"] = MagicMock()
        pool.invalidate_all()
        assert pool._clients == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/core/test_llm_client_pool.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.core.llm_client_pool'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/core/llm_client_pool.py

import asyncio
from typing import Dict
from openai import AsyncOpenAI
from src.config.llm_profiles import LLMProfile


class LLMClientPool:
    def __init__(self):
        self._clients: Dict[str, AsyncOpenAI] = {}
        self._lock = asyncio.Lock()

    async def get_client(self, profile: LLMProfile) -> AsyncOpenAI:
        async with self._lock:
            if profile.name not in self._clients:
                self._clients[profile.name] = AsyncOpenAI(
                    api_key=profile.api_key,
                    base_url=profile.base_url,
                )
            return self._clients[profile.name]

    def invalidate(self, profile_name: str) -> None:
        self._clients.pop(profile_name, None)

    def invalidate_all(self) -> None:
        self._clients.clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/core/test_llm_client_pool.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/llm_client_pool.py tests/unit/core/test_llm_client_pool.py
git commit -m "feat: add LLMClientPool for cached AsyncOpenAI instances"
```

---

## Task 4: Add `routing_hint` to `call_llm()` + `init_llm_infrastructure()`

**Files:**
- Modify: `src/core/llm_client.py`
- Modify: `tests/unit/core/test_llm_client.py`

- [ ] **Step 1: Write failing tests for routing hint in call_llm**

```python
# Add to tests/unit/core/test_llm_client.py (append new class)

from src.config.llm_profiles import LLMProfile, LLMProfileRegistry, RoutingHint
from src.core.llm_router import LLMRouter
from src.core.llm_client_pool import LLMClientPool


def _make_registry_for_routing():
    strong = LLMProfile(name="strong", model="gpt-4o", api_key="sk-strong", base_url="https://strong.api.com/v1", temperature=0.3, max_tokens=8000, top_p=1.0, frequency_penalty=0.0, presence_penalty=0.0, enabled=True)
    fast = LLMProfile(name="fast", model="deepseek-v4-flash", api_key="sk-fast", base_url="https://fast.api.com/v1", temperature=0.5, max_tokens=4096, top_p=1.0, frequency_penalty=0.0, presence_penalty=0.0, is_default=True, enabled=True)
    return LLMProfileRegistry(
        profiles={"strong": strong, "fast": fast},
        default_profile="fast",
        fallback_chain=["strong", "fast"],
        fixed_agent_routing={"quality_check": "strong"},
        action_routing={"analyze": "strong", "search": "fast"},
    )


class TestCallLlmWithRoutingHint:
    @pytest.mark.asyncio
    async def test_routing_hint_none_uses_legacy_path(self):
        ms = _mock_settings()
        with patch("src.core.llm_client.settings", ms):
            with patch("src.core.llm_client._call_llm_api", new_callable=AsyncMock) as mock_api:
                mock_api.return_value = {"choices": [{"message": {"content": "ok"}}], "usage": {}}
                from src.core.llm_client import call_llm
                result = await call_llm(prompt="test", routing_hint=None)
                assert result["success"] is True
                call_kwargs = mock_api.call_args[1]
                assert call_kwargs["api_key"] == "test-key"

    @pytest.mark.asyncio
    async def test_routing_hint_resolves_profile(self):
        from src.core.llm_client import call_llm, init_llm_infrastructure
        registry = _make_registry_for_routing()
        init_llm_infrastructure(registry)
        with patch("src.core.llm_client._call_llm_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"choices": [{"message": {"content": "ok"}}], "usage": {}}
            hint = RoutingHint(profile_name="strong")
            result = await call_llm(prompt="test", routing_hint=hint)
            assert result["success"] is True
            call_kwargs = mock_api.call_args[1]
            assert call_kwargs["model"] == "gpt-4o"
            assert call_kwargs["api_key"] == "sk-strong"
            assert call_kwargs["base_url"] == "https://strong.api.com/v1"
            assert call_kwargs["temperature"] == 0.3
            assert call_kwargs["max_tokens"] == 8000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/core/test_llm_client.py::TestCallLlmWithRoutingHint -v`
Expected: FAIL — `TypeError: call_llm() got an unexpected keyword argument 'routing_hint'`

- [ ] **Step 3: Write minimal implementation — add routing_hint param and routing logic to call_llm**

Modify `src/core/llm_client.py` — add imports at top, add `init_llm_infrastructure` function, add `routing_hint` parameter to `call_llm`, and insert routing path logic before the existing legacy path. The routing logic must use the existing `_call_llm_api()` helper and `_parse_response()` — no new pseudo-code functions.

Key change: when `_router is not None and routing_hint is not None`, resolve profile via router, get client from pool, call `_call_llm_api()` with profile's api_key/base_url/model. When `routing_hint is None` (or `_router is None`), the existing `settings.llm.*` path runs unchanged.

The exact code for the routing path insertion (between the empty-prompt check and the existing `model = model or settings.llm.model` line) is in the design spec section 3.6.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/core/test_llm_client.py::TestCallLlmWithRoutingHint -v`
Expected: PASS

Also run: `pytest tests/unit/core/test_llm_client.py -v`
Expected: ALL PASS (existing tests unchanged)

- [ ] **Step 5: Commit**

```bash
git add src/core/llm_client.py tests/unit/core/test_llm_client.py
git commit -m "feat: add routing_hint param to call_llm with backward compat"
```

---

## Task 5: Settings Profile Integration — CRUD, Persistence, Migration, Sync

**Files:**
- Modify: `src/config/settings.py`
- Modify: `tests/unit/config/conftest.py`
- Modify: `tests/unit/config/test_settings.py`

- [ ] **Step 1: Write failing tests for Settings profile methods**

```python
# Add to tests/unit/config/test_settings.py (append new classes)

from src.config.llm_profiles import LLMProfile, LLMProfileRegistry, RoutingHint


class TestSettingsProfileCRUD:
    @patch.dict(os.environ, _ENV_DEFAULTS, clear=True)
    def test_get_profile_returns_profile(self):
        settings = Settings(config_path="nonexistent.toml")
        settings.llm_profiles.profiles["strong"] = LLMProfile(name="strong", model="gpt-4o")
        result = settings.get_profile("strong")
        assert result is not None
        assert result.model == "gpt-4o"

    @patch.dict(os.environ, _ENV_DEFAULTS, clear=True)
    def test_get_profile_returns_none_for_missing(self):
        settings = Settings(config_path="nonexistent.toml")
        assert settings.get_profile("nonexistent") is None

    @patch.dict(os.environ, _ENV_DEFAULTS, clear=True)
    def test_get_default_profile(self):
        settings = Settings(config_path="nonexistent.toml")
        fast = LLMProfile(name="fast", is_default=True, enabled=True)
        settings.llm_profiles.profiles["fast"] = fast
        settings.llm_profiles.default_profile = "fast"
        result = settings.get_default_profile()
        assert result is not None
        assert result.name == "fast"

    @patch.dict(os.environ, _ENV_DEFAULTS, clear=True)
    def test_update_profile_creates_new(self):
        settings = Settings(config_path="nonexistent.toml")
        profile = settings.update_profile("strong", {
            "display_name": "GPT-4o Strong",
            "provider": "openai",
            "model": "gpt-4o",
            "temperature": 0.3,
            "max_tokens": 8000,
        })
        assert profile.name == "strong"
        assert profile.model == "gpt-4o"
        assert profile.temperature == 0.3
        assert "strong" in settings.llm_profiles.profiles

    @patch.dict(os.environ, _ENV_DEFAULTS, clear=True)
    def test_update_profile_updates_existing(self):
        settings = Settings(config_path="nonexistent.toml")
        settings.llm_profiles.profiles["fast"] = LLMProfile(name="fast", model="deepseek-v4-flash")
        profile = settings.update_profile("fast", {"model": "deepseek-v4-pro", "temperature": 0.5})
        assert profile.model == "deepseek-v4-pro"
        assert profile.temperature == 0.5

    @patch.dict(os.environ, _ENV_DEFAULTS, clear=True)
    def test_update_profile_maps_api_endpoint_to_base_url(self):
        settings = Settings(config_path="nonexistent.toml")
        profile = settings.update_profile("test", {"api_endpoint": "https://custom.api.com/v1"})
        assert profile.base_url == "https://custom.api.com/v1"

    @patch.dict(os.environ, _ENV_DEFAULTS, clear=True)
    def test_delete_profile_cannot_delete_default(self):
        settings = Settings(config_path="nonexistent.toml")
        settings.llm_profiles.profiles["fast"] = LLMProfile(name="fast", is_default=True)
        settings.llm_profiles.default_profile = "fast"
        result = settings.delete_profile("fast")
        assert result is False

    @patch.dict(os.environ, _ENV_DEFAULTS, clear=True)
    def test_delete_profile_removes_non_default(self):
        settings = Settings(config_path="nonexistent.toml")
        settings.llm_profiles.profiles["local"] = LLMProfile(name="local")
        settings.llm_profiles.default_profile = "fast"
        result = settings.delete_profile("local")
        assert result is True
        assert "local" not in settings.llm_profiles.profiles

    @patch.dict(os.environ, _ENV_DEFAULTS, clear=True)
    def test_set_default_profile(self):
        settings = Settings(config_path="nonexistent.toml")
        settings.llm_profiles.profiles["strong"] = LLMProfile(name="strong")
        settings.llm_profiles.profiles["fast"] = LLMProfile(name="fast", is_default=True)
        settings.llm_profiles.default_profile = "fast"
        settings.set_default_profile("strong")
        assert settings.llm_profiles.default_profile == "strong"
        assert settings.llm_profiles.profiles["strong"].is_default is True
        assert settings.llm_profiles.profiles["fast"].is_default is False


class TestSettingsProfileSync:
    @patch.dict(os.environ, _ENV_DEFAULTS, clear=True)
    def test_sync_updates_llm_config_from_default_profile(self):
        settings = Settings(config_path="nonexistent.toml")
        settings.llm_profiles.profiles["fast"] = LLMProfile(
            name="fast", provider="deepseek", model="deepseek-v4-flash",
            api_key="sk-fast", base_url="https://api.deepseek.com/v1",
            temperature=0.5, max_tokens=4096,
        )
        settings.llm_profiles.default_profile = "fast"
        settings._sync_llm_config_from_profiles()
        assert settings.llm.provider == "deepseek"
        assert settings.llm.model == "deepseek-v4-flash"
        assert settings.llm.api_key == "sk-fast"
        assert settings.llm.base_url == "https://api.deepseek.com/v1"
        assert settings.llm.temperature == 0.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/config/test_settings.py::TestSettingsProfileCRUD -v`
Expected: FAIL — `AttributeError: Settings instance has no attribute 'llm_profiles'`

- [ ] **Step 3: Write minimal implementation — modify Settings class**

Modify `src/config/settings.py`:
1. Add `from src.config.llm_profiles import LLMProfile, LLMProfileRegistry` import
2. Add `self.llm_profiles = LLMProfileRegistry()` in `__init__`
3. Add the profile CRUD methods (get_profile, get_default_profile, update_profile, delete_profile, set_default_profile) — exact implementation from the design spec section 3.9
4. Add `_sync_llm_config_from_profiles()` — exact implementation from the design spec
5. Call `_sync_llm_config_from_profiles()` at the end of `_load_config()`

Also update `tests/unit/config/conftest.py` to clean `data/llm_profiles.json`:

```python
# tests/unit/config/conftest.py

from pathlib import Path
import pytest
from src.config.settings import Settings


@pytest.fixture(autouse=True)
def reset_settings():
    _clean_persist()
    Settings._reset_instance()
    yield
    Settings._reset_instance()
    _clean_persist()


def _clean_persist():
    for path in [Path("data/llm_config.json"), Path("data/llm_profiles.json")]:
        if path.exists():
            path.unlink()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/config/test_settings.py -v`
Expected: ALL PASS (both new and existing tests)

- [ ] **Step 5: Commit**

```bash
git add src/config/settings.py tests/unit/config/test_settings.py tests/unit/config/conftest.py
git commit -m "feat: add LLMProfileRegistry and profile CRUD to Settings"
```

---

## Task 6: Profile Disk Persistence and Migration

**Files:**
- Modify: `src/config/settings.py` (add _persist_llm_profiles, _load_llm_profiles_from_disk, _migrate_legacy_llm_config)
- Modify: `tests/unit/config/test_settings.py`

- [ ] **Step 1: Write failing tests for profile persistence and migration**

```python
# Add to tests/unit/config/test_settings.py

class TestSettingsProfileDiskPersistence:
    @patch.dict(os.environ, _ENV_DEFAULTS, clear=True)
    def test_update_profile_persists_to_disk(self):
        settings = Settings(config_path="nonexistent.toml")
        persist_path = Path("data/llm_profiles.json")
        if persist_path.exists():
            persist_path.unlink()

        settings.update_profile("strong", {"model": "gpt-4o", "provider": "openai", "api_key": "sk-xxx"})

        assert persist_path.exists()
        data = json.loads(persist_path.read_text(encoding="utf-8"))
        assert data["version"] == 2
        assert "strong" in data["profiles"]
        assert data["profiles"]["strong"]["model"] == "gpt-4o"

        persist_path.unlink(missing_ok=True)

    @patch.dict(os.environ, _ENV_DEFAULTS, clear=True)
    def test_disk_persistence_survives_new_instance(self):
        persist_path = Path("data/llm_profiles.json")
        persist_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 2,
            "profiles": {
                "fast": {
                    "name": "fast", "display_name": "Fast", "provider": "deepseek",
                    "api_key": "sk-fast", "base_url": "https://api.deepseek.com/v1",
                    "model": "deepseek-v4-flash", "temperature": 0.5,
                    "max_tokens": 4096, "top_p": 1.0, "frequency_penalty": 0.0,
                    "presence_penalty": 0.0, "max_context_tokens": 128000,
                    "cost_limit_per_call": 0.1, "is_default": True, "enabled": True,
                    "created_at": "", "updated_at": "",
                }
            },
            "default_profile": "fast",
            "fallback_chain": ["strong", "fast"],
            "routing": {"fixed_agents": {}, "actions": {}},
        }
        persist_path.write_text(json.dumps(data), encoding="utf-8")

        Settings._reset_instance()
        new_settings = Settings(config_path="nonexistent.toml")
        assert new_settings.llm_profiles.profiles["fast"].model == "deepseek-v4-flash"
        assert new_settings.llm_profiles.default_profile == "fast"

        persist_path.unlink(missing_ok=True)


class TestSettingsLegacyMigration:
    @patch.dict(os.environ, _ENV_DEFAULTS, clear=True)
    def test_migrate_legacy_llm_config(self):
        old_path = Path("data/llm_config.json")
        new_path = Path("data/llm_profiles.json")
        old_path.parent.mkdir(parents=True, exist_ok=True)

        if new_path.exists():
            new_path.unlink()

        old_data = {
            "provider": "deepseek", "model": "deepseek-v4-pro",
            "api_key": "sk-migrated", "api_endpoint": "https://api.deepseek.com/v1",
            "temperature": 0.5, "max_tokens": 4096, "top_p": 1.0,
            "frequency_penalty": 0.0, "presence_penalty": 0.0,
            "cheap_model": "deepseek-v4-flash", "embedding_model": "text-embedding-3-small",
        }
        old_path.write_text(json.dumps(old_data), encoding="utf-8")

        Settings._reset_instance()
        settings = Settings(config_path="nonexistent.toml")

        assert "migrated" in settings.llm_profiles.profiles
        assert settings.llm_profiles.profiles["migrated"].provider == "deepseek"
        assert settings.llm_profiles.profiles["migrated"].model == "deepseek-v4-pro"
        assert settings.llm_profiles.profiles["migrated"].api_key == "sk-migrated"
        assert settings.llm_profiles.profiles["migrated"].base_url == "https://api.deepseek.com/v1"
        assert settings.llm_profiles.default_profile == "migrated"
        assert new_path.exists()

        old_path.unlink(missing_ok=True)
        new_path.unlink(missing_ok=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/config/test_settings.py::TestSettingsProfileDiskPersistence -v`
Expected: FAIL — `AttributeError` or persistence not working yet

- [ ] **Step 3: Write minimal implementation**

Add `_persist_llm_profiles()`, `_load_llm_profiles_from_disk()`, `_migrate_legacy_llm_config()` methods to Settings class. Call them in `_load_config()` in the correct order (after env/YAML loading). Exact implementations from the design spec section 3.9.

Also update `_load_config()` to call `_load_llm_profiles_from_yaml()` (skip if no YAML file exists), `_load_llm_profiles_from_disk()`, `_migrate_legacy_llm_config()`, `_sync_llm_config_from_profiles()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/config/test_settings.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add src/config/settings.py tests/unit/config/test_settings.py
git commit -m "feat: add profile disk persistence and legacy migration"
```

---

## Task 7: Configuration YAML Files

**Files:**
- Create: `config/llm_profiles.yaml`
- Create: `config/llm_routing.yaml`
- Add to `.env.example`: new env vars

- [ ] **Step 1: Create `config/llm_profiles.yaml`**

Create the file with exact content from the design spec section 3.7.1 (using `${VAR_NAME}` syntax only, no `${VAR:default}`).

- [ ] **Step 2: Create `config/llm_routing.yaml`**

Create the file with exact content from the design spec section 3.7.2.

- [ ] **Step 3: Add new env vars to `.env.example`**

Add the env vars listed in the design spec section 3.7.1 under "Required `.env` additions".

- [ ] **Step 4: Write test for YAML loading**

```python
# Add to tests/unit/config/test_settings.py

class TestSettingsYamlProfileLoading:
    @patch.dict(os.environ, {
        "LLM_STRONG_API_KEY": "sk-strong",
        "LLM_STRONG_BASE_URL": "https://api.openai.com/v1",
        "LLM_STRONG_MODEL": "gpt-4o",
        "LLM_FAST_API_KEY": "sk-fast",
        "LLM_FAST_BASE_URL": "https://api.deepseek.com/v1",
        "LLM_FAST_MODEL": "deepseek-v4-flash",
        "LLM_LOCAL_BASE_URL": "http://localhost:11434/v1",
        "LLM_LOCAL_MODEL": "qwen2.5",
    }, clear=True)
    def test_loads_profiles_from_yaml(self):
        settings = Settings(config_path="nonexistent.toml")
        settings._load_llm_profiles_from_yaml()
        assert "strong" in settings.llm_profiles.profiles
        assert settings.llm_profiles.profiles["strong"].model == "gpt-4o"
        assert "fast" in settings.llm_profiles.profiles
        assert settings.llm_profiles.profiles["fast"].model == "deepseek-v4-flash"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/config/test_settings.py::TestSettingsYamlProfileLoading -v`
Expected: PASS (YAML files exist and env vars are set)

- [ ] **Step 6: Commit**

```bash
git add config/llm_profiles.yaml config/llm_routing.yaml .env.example tests/unit/config/test_settings.py
git commit -m "feat: add llm_profiles.yaml and llm_routing.yaml config files"
```

---

## Task 8: `init_llm_infrastructure()` in App Startup

**Files:**
- Modify: `src/api/main.py`

- [ ] **Step 1: Add `init_llm_infrastructure()` call to startup event**

In `src/api/main.py`, inside the `@app.on_event("startup")` handler (line 973), add after the existing `register_global_exception_handler()` call:

```python
from src.config.llm_profiles import LLMProfileRegistry
from src.core.llm_client import init_llm_infrastructure

init_llm_infrastructure(settings.llm_profiles)
logger.info("LLM infrastructure initialized with %d profiles", len(settings.llm_profiles.profiles))
```

- [ ] **Step 2: Verify app still starts**

Run: `python -c "from src.api.main import app; print('OK')"`
Expected: OK (no import errors, startup event not actually triggered in this test)

- [ ] **Step 3: Commit**

```bash
git add src/api/main.py
git commit -m "feat: add init_llm_infrastructure to app startup"
```

---

## Task 9: Profile/Routing API Endpoints

**Files:**
- Modify: `src/api/main.py`
- Create: `tests/unit/api/test_llm_profiles_api.py`

- [ ] **Step 1: Write failing tests for profile API endpoints**

```python
# tests/unit/api/test_llm_profiles_api.py

import pytest
import json
from pathlib import Path
from fastapi.testclient import TestClient
from unittest.mock import patch
import os


_ENV_DEFAULTS = {
    "LLM_PROVIDER": "test-provider",
    "LLM_MODEL": "test-model",
    "LLM_API_KEY": "test-api-key",
    "LLM_BASE_URL": "https://test.api.com/v1",
    "LLM_CHEAP_MODEL": "test-cheap",
    "LLM_EMBEDDING_MODEL": "test-embedding",
}


@pytest.fixture
def client():
    from src.config.settings import Settings
    Settings._reset_instance()
    for p in [Path("data/llm_config.json"), Path("data/llm_profiles.json")]:
        if p.exists():
            p.unlink()
    with patch.dict(os.environ, _ENV_DEFAULTS, clear=True):
        from src.api.main import app
        tc = TestClient(app)
        yield tc
    Settings._reset_instance()
    for p in [Path("data/llm_config.json"), Path("data/llm_profiles.json")]:
        if p.exists():
            p.unlink()


class TestProfileAPI:
    def test_list_profiles(self, client):
        resp = client.get("/api/v1/llm/profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_create_profile(self, client):
        resp = client.post("/api/v1/llm/profiles", json={
            "name": "custom",
            "display_name": "Custom Model",
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_key": "sk-custom",
            "base_url": "https://api.openai.com/v1",
            "temperature": 0.5,
            "max_tokens": 4096,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "custom"
        assert data["model"] == "gpt-4o-mini"

    def test_get_single_profile(self, client):
        client.post("/api/v1/llm/profiles", json={
            "name": "test", "provider": "openai", "model": "gpt-4o", "api_key": "sk-test",
        })
        resp = client.get("/api/v1/llm/profiles/test")
        assert resp.status_code == 200
        assert resp.json()["name"] == "test"

    def test_get_nonexistent_profile_returns_404(self, client):
        resp = client.get("/api/v1/llm/profiles/nonexistent")
        assert resp.status_code == 404

    def test_update_profile(self, client):
        client.post("/api/v1/llm/profiles", json={
            "name": "test", "provider": "openai", "model": "gpt-4o", "api_key": "sk-test",
        })
        resp = client.put("/api/v1/llm/profiles/test", json={"model": "gpt-4o-mini", "temperature": 0.3})
        assert resp.status_code == 200
        assert resp.json()["model"] == "gpt-4o-mini"

    def test_delete_non_default_profile(self, client):
        client.post("/api/v1/llm/profiles", json={
            "name": "extra", "provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-extra",
        })
        resp = client.delete("/api/v1/llm/profiles/extra")
        assert resp.status_code == 200

    def test_delete_default_profile_fails(self, client):
        client.post("/api/v1/llm/profiles", json={
            "name": "default", "provider": "openai", "model": "gpt-4o", "api_key": "sk-default",
        })
        client.post("/api/v1/llm/profiles/default/default")
        resp = client.delete("/api/v1/llm/profiles/default")
        assert resp.status_code in [400, 403]

    def test_set_default_profile(self, client):
        client.post("/api/v1/llm/profiles", json={
            "name": "strong", "provider": "openai", "model": "gpt-4o", "api_key": "sk-strong",
        })
        resp = client.post("/api/v1/llm/profiles/strong/default")
        assert resp.status_code == 200

    def test_toggle_profile_enabled(self, client):
        client.post("/api/v1/llm/profiles", json={
            "name": "local", "provider": "local", "model": "qwen2.5", "api_key": "",
        })
        resp = client.post("/api/v1/llm/profiles/local/toggle")
        assert resp.status_code == 200

    def test_get_routing_config(self, client):
        resp = client.get("/api/v1/llm/routing")
        assert resp.status_code == 200
        data = resp.json()
        assert "default_profile" in data
        assert "fallback_chain" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/api/test_llm_profiles_api.py -v`
Expected: FAIL — 404 on `/api/v1/llm/profiles` (endpoints don't exist yet)

- [ ] **Step 3: Write minimal implementation — add API endpoints to main.py**

Add the following endpoints to `src/api/main.py`:
- `GET /api/v1/llm/profiles` — list all profiles (api_key redacted as `hasApiKey`)
- `GET /api/v1/llm/profiles/{name}` — get single profile
- `POST /api/v1/llm/profiles` — create profile
- `PUT /api/v1/llm/profiles/{name}` — update profile
- `DELETE /api/v1/llm/profiles/{name}` — delete profile (cannot delete default)
- `POST /api/v1/llm/profiles/{name}/default` — set as default
- `POST /api/v1/llm/profiles/{name}/toggle` — toggle enabled
- `GET /api/v1/llm/routing` — get routing config
- `PUT /api/v1/llm/routing` — update routing config

Each endpoint uses `settings` singleton's profile methods.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/api/test_llm_profiles_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/api/main.py tests/unit/api/test_llm_profiles_api.py
git commit -m "feat: add multi-profile and routing API endpoints"
```

---

## Task 10: Modify `agents.yaml` — Replace `llm` with `llm_profile`

**Files:**
- Modify: `config/agents.yaml`
- Modify: `src/config/agents.py`

- [ ] **Step 1: Update `config/agents.yaml`**

Replace each agent's `llm:` section with `llm_profile:` reference. Keep all other sections (capabilities, templates, etc.) unchanged. Example:

```yaml
requirement_analysis:
  llm_profile: strong
  capabilities:
    - Industry Identification
    ...

report_generation:
  llm_profile: strong
  capabilities:
    ...

quality_check:
  llm_profile: strong
  ...

data_collection:
  llm_profile: fast
  ...
```

- [ ] **Step 2: Update `src/config/agents.py` AgentLLMConfig**

Replace `AgentLLMConfig` with a simpler structure that has `profile_name` instead of `model/temperature/max_tokens`. Update `_parse_agent_config()` to read `llm_profile` instead of `llm`.

- [ ] **Step 3: Verify existing tests still pass**

Run: `pytest tests/unit/ -v --tb=short`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add config/agents.yaml src/config/agents.py
git commit -m "feat: replace per-agent llm config with llm_profile reference"
```

---

## Verification Checklist

After all tasks complete, run:

```bash
pytest tests/unit/ -v --tb=short
pytest tests/unit/config/ -v
pytest tests/unit/core/ -v
pytest tests/unit/api/ -v
```

All must pass with zero failures and zero errors.

---

**Plan complete and saved to `docs/superpowers/plans/2026-07-01-multi-llm-routing.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
