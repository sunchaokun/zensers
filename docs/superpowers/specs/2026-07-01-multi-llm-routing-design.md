# Multi-LLM Profile & Intelligent Routing Design

**Date**: 2026-07-01
**Status**: In Progress (Phase 1 — Backend Infrastructure)
**Scope**: Backend + Frontend

---

## Implementation Progress

| Task | Status | Tests | Commit |
|------|--------|-------|--------|
| Task 1: LLMProfile/Registry/RoutingHint dataclasses | ✅ Done | 7 passed | e88ed4f |
| Task 2: LLMRouter 5-level routing | ✅ Done | 17 passed | 98d8f53 |
| Task 3: LLMClientPool | 🔲 Pending | — | — |
| Task 4: call_llm() + routing_hint | 🔲 Pending | — | — |
| Task 5: Settings Profile CRUD + Sync | 🔲 Pending | — | — |
| Task 6: Profile disk persistence + migration | 🔲 Pending | — | — |
| Task 7: YAML config files | 🔲 Pending | — | — |
| Task 8: App startup init | 🔲 Pending | — | — |
| Task 9: Profile/Routing API endpoints | 🔲 Pending | — | — |
| Task 10: agents.yaml llm_profile | 🔲 Pending | — | — |

**New files created:** `src/config/llm_profiles.py`, `src/core/llm_router.py`, `tests/unit/config/test_llm_profiles.py`, `tests/unit/core/test_llm_router.py`

---

## 1. Problem Statement

### 1.1 Current Issues

1. **Single global LLM config**: `Settings` singleton holds one `LLMConfig`, all agents share it. Every `update_from_request()` overwrites the global state and persists to disk — one user's change affects all sessions.

2. **Per-agent LLM config is dead code**: `config/agents.yaml` defines per-agent `model/temperature/max_tokens`, `src/config/agents.py` loads them into `AgentLLMConfig`, but **nothing consumes these at runtime**. All LLM calls go through `settings.llm.*`.

3. **Five inconsistent LLM call patterns**:
   - `call_llm()` in `src/core/llm_client.py` — the recommended centralized path
   - `LLMSkill` in `src/skills/llm_skill.py` — skill wrapper with nearly identical logic, used extensively in `research_api.py`, `task_structure.py`, `semantic_intent.py`, `revision_intent_analyzer.py`, `translate_operation.py`, `findings.py`, `batch_revision_service.py`
   - `GenericAgent._call_llm_directly()` in `src/core/agents/generic_agent.py` (line 4302) — creates its own `AsyncOpenAI` client using `settings.llm.*`
   - Direct `AsyncOpenAI` in quality layers: `layer3_depth.py` (line 208) and `llm_judge.py` (line 70) — bypass all abstraction, create new client on every call
   - `layer2_methodology.py` — uses dependency injection (`llm_client` param), but typically receives `None`, falling back to non-LLM heuristics

4. **Dynamic agents have no LLM identity**: `GenericAgent` handles multiple action types (search, analyze, generate, etc.) but always uses the global config via `settings.llm.*`. It has its own `_call_llm_directly()` method (line 4302) that creates a fresh `AsyncOpenAI` client on every call, bypassing `call_llm()`. There's no way to route different actions to different models.

5. **Frontend config is single-profile**: The settings page saves one LLM config to `data/llm_config.json` and localStorage. Saving a new config **replaces** the old one entirely.

6. **Per-request config overwrites global state**: Research API endpoints accept LLM form fields and call `settings.update_from_request()`, permanently modifying the singleton for all users.

7. **Vision/embedding/cost fields not persisted**: `vision_model`, `vision_api_key`, `vision_base_url`, `max_context_tokens`, `cost_limit_per_report` are lost on restart.

### 1.2 Goals

- Support **multiple LLM profiles** (e.g., "strong" for reasoning, "fast" for utility, "local" for privacy)
- **Intelligent routing**: fixed agents by explicit config, dynamic agents by action/skill type with keyword auto-classification
- **Fallback chains**: if a profile fails, automatically try the next one
- **Frontend multi-profile management**: create, edit, delete profiles without overwriting each other
- **Unified LLM call path**: eliminate the five inconsistent patterns
- **Session-scoped config**: per-request LLM changes should NOT overwrite global state

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Callers                                   │
│  FixedAgent / GenericAgent / API / Quality Layer / Skill         │
└────────────────────────┬────────────────────────────────────────┘
                         │ call_llm(prompt, ..., routing_hint=...)
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                   LLMRouter (智能路由器)                          │
│  resolve(routing_hint) → profile_name                            │
│                                                                  │
│  Priority:                                                       │
│  1. Explicit override (caller-specified profile_name)            │
│  2. Fixed agent mapping (agent_type → profile)                   │
│  3. Action/skill mapping (action → profile)                      │
│  4. Keyword auto-classification (action name → reasoning/utility)│
│  5. Fallback default profile                                     │
└────────────────────────┬────────────────────────────────────────┘
                         │ profile_name
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              LLMProfileRegistry (Profile 池)                     │
│                                                                  │
│  "strong"  → LLMProfile { provider, api_key, base_url, model,   │
│              temperature, max_tokens, top_p, ... }               │
│  "fast"    → LLMProfile { ... }                                  │
│  "local"   → LLMProfile { ... }                                  │
│  "vision"  → LLMProfile { ... }                                  │
│                                                                  │
│  + fallback_chain: ["strong", "fast", "local"]                   │
│  + default_profile: "fast"                                       │
└────────────────────────┬────────────────────────────────────────┘
                         │ LLMProfile
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│               LLMClientPool (客户端池)                            │
│                                                                  │
│  profile_name → cached AsyncOpenAI instance                      │
│  Lazy creation, connection reuse, thread-safe                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Backend Design

### 3.1 New Data Model: `LLMProfile`

Replace the single `LLMConfig` with a collection of named `LLMProfile` instances.

```python
# src/config/llm_profiles.py

@dataclass
class LLMProfile:
    """A named LLM configuration profile."""
    name: str                          # Unique identifier, e.g. "strong", "fast"
    display_name: str = ""             # Human-readable name, e.g. "GPT-4o (Strong)"
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
    cost_limit_per_call: float = 0.0   # 0 = no limit
    is_default: bool = False           # Is this the fallback profile?
    enabled: bool = True               # Can be disabled without deletion
    created_at: str = ""               # ISO timestamp
    updated_at: str = ""               # ISO timestamp
```

Key differences from current `LLMConfig`:
- `name` — unique identifier for routing
- `display_name` — for frontend display
- `is_default` — marks the fallback profile
- `enabled` — soft-disable without losing config
- `cost_limit_per_call` — per-profile cost control (replaces global `cost_limit_per_report`)
- Timestamps for audit

### 3.2 New Data Model: `LLMProfileRegistry`

```python
# src/config/llm_profiles.py

@dataclass
class LLMProfileRegistry:
    """Collection of all LLM profiles + routing config."""
    profiles: Dict[str, LLMProfile] = field(default_factory=dict)
    default_profile: str = "fast"                    # Fallback profile name
    fallback_chain: List[str] = field(default_factory=lambda: ["strong", "fast", "local"])
    
    # Routing rules
    fixed_agent_routing: Dict[str, str] = field(default_factory=dict)   # agent_type → profile_name
    action_routing: Dict[str, str] = field(default_factory=dict)        # action/skill → profile_name
```

### 3.3 New Data Model: `RoutingHint`

Passed by callers to `call_llm()` to help the router decide:

```python
@dataclass
class RoutingHint:
    """Hint for the LLM router to select the right profile."""
    agent_type: Optional[str] = None     # e.g. "requirement_analysis", "quality_check"
    action: Optional[str] = None         # e.g. "llm_skill", "search", "analyze"
    profile_name: Optional[str] = None   # Explicit override, bypasses routing
    force_profile: bool = False          # If True, use profile_name even if disabled
```

### 3.4 LLMRouter

```python
# src/core/llm_router.py

class LLMRouter:
    """Intelligent LLM profile router."""
    
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
        """
        Resolve routing hint to a concrete LLMProfile.
        
        Priority:
        1. Explicit profile_name override (if force_profile or profile is enabled)
        2. Fixed agent mapping (hint.agent_type → profile)
        3. Action/skill mapping (hint.action → profile)
        4. Keyword auto-classification (action name → reasoning/utility → profile)
        5. Default profile fallback
        """
        # 1. Explicit override
        if hint.profile_name:
            profile = self.registry.profiles.get(hint.profile_name)
            if profile and (hint.force_profile or profile.enabled):
                return profile
        
        # 2. Fixed agent mapping
        if hint.agent_type:
            profile_name = self.registry.fixed_agent_routing.get(hint.agent_type)
            if profile_name:
                profile = self.registry.profiles.get(profile_name)
                if profile and profile.enabled:
                    return profile
        
        # 3. Action/skill mapping
        if hint.action:
            profile_name = self.registry.action_routing.get(hint.action)
            if profile_name:
                profile = self.registry.profiles.get(profile_name)
                if profile and profile.enabled:
                    return profile
        
        # 4. Keyword auto-classification
        if hint.action:
            action_lower = hint.action.lower()
            if any(kw in action_lower for kw in self.REASONING_KEYWORDS):
                # Reasoning tasks → "strong" profile (if exists and enabled)
                for name in ["strong", "default"]:
                    profile = self.registry.profiles.get(name)
                    if profile and profile.enabled:
                        return profile
            elif any(kw in action_lower for kw in self.UTILITY_KEYWORDS):
                # Utility tasks → "fast" profile (if exists and enabled)
                for name in ["fast", "default"]:
                    profile = self.registry.profiles.get(name)
                    if profile and profile.enabled:
                        return profile
        
        # 5. Default profile
        default = self.registry.profiles.get(self.registry.default_profile)
        if default and default.enabled:
            return default
        
        # 6. Any enabled profile
        for profile in self.registry.profiles.values():
            if profile.enabled:
                return profile
        
        raise RuntimeError("No enabled LLM profile available")
```

### 3.5 LLMClientPool

```python
# src/core/llm_client_pool.py

class LLMClientPool:
    """Pool of cached AsyncOpenAI clients, one per profile."""
    
    def __init__(self):
        self._clients: Dict[str, AsyncOpenAI] = {}
        self._lock = asyncio.Lock()
    
    async def get_client(self, profile: LLMProfile) -> AsyncOpenAI:
        """Get or create an AsyncOpenAI client for the given profile."""
        async with self._lock:
            if profile.name not in self._clients:
                self._clients[profile.name] = AsyncOpenAI(
                    api_key=profile.api_key,
                    base_url=profile.base_url,
                )
            return self._clients[profile.name]
    
    def invalidate(self, profile_name: str) -> None:
        """Remove cached client (called when profile config changes)."""
        self._clients.pop(profile_name, None)
    
    def invalidate_all(self) -> None:
        """Remove all cached clients."""
        self._clients.clear()
```

### 3.6 Unified `call_llm()` Redesign

The new `call_llm()` accepts `RoutingHint` and delegates to the router. The existing function signature in `src/core/llm_client.py` is extended, not replaced.

**Current signature** (lines 72-81):
```python
async def call_llm(
    prompt: str,
    model: Optional[str] = None,
    system_prompt: str = "",
    fallback_model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
```

**New signature** — adds `routing_hint` parameter, preserves all existing params:
```python
from src.config.llm_profiles import LLMProfile, LLMProfileRegistry, RoutingHint
from src.core.llm_router import LLMRouter
from src.core.llm_client_pool import LLMClientPool

_router: Optional[LLMRouter] = None
_client_pool: Optional[LLMClientPool] = None

def init_llm_infrastructure(registry: LLMProfileRegistry):
    """Initialize the global router and client pool. Called at app startup."""
    global _router, _client_pool
    _router = LLMRouter(registry)
    _client_pool = LLMClientPool()

async def call_llm(
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
```

**Routing logic** — inserted before the existing `settings.llm.*` fallback:

```python
    if not prompt or not prompt.strip():
        return {"success": False, "message": "prompt cannot be empty", "error": "empty_prompt"}

    # --- NEW: Routing path ---
    if _router is not None and routing_hint is not None:
        hint = routing_hint
        profile = _router.resolve(hint)
        client = await _client_pool.get_client(profile)

        actual_model = model or profile.model
        actual_max_tokens = max_tokens or profile.max_tokens
        actual_temperature = temperature if temperature is not None else profile.temperature

        if profile.cost_limit_per_call > 0:
            estimated_cost = (actual_max_tokens / 1000) * 0.01
            if estimated_cost > profile.cost_limit_per_call:
                return {"success": False, "message": "Cost limit exceeded", "error": "cost_limit"}

        try:
            response = await _call_llm_api(
                prompt=prompt, model=actual_model, system_prompt=system_prompt,
                max_tokens=actual_max_tokens, temperature=actual_temperature,
                api_key=profile.api_key, base_url=profile.base_url)
            return _parse_response(response, actual_model)
        except Exception as primary_err:
            for fallback_name in _router.registry.fallback_chain:
                if fallback_name == profile.name:
                    continue
                fb_profile = _router.registry.profiles.get(fallback_name)
                if not fb_profile or not fb_profile.enabled:
                    continue
                try:
                    fb_client = await _client_pool.get_client(fb_profile)
                    fb_model = model or fb_profile.model
                    response = await _call_llm_api(
                        prompt=prompt, model=fb_model, system_prompt=system_prompt,
                        max_tokens=max_tokens or fb_profile.max_tokens,
                        temperature=temperature if temperature is not None else fb_profile.temperature,
                        api_key=fb_profile.api_key, base_url=fb_profile.base_url)
                    result = _parse_response(response, fb_model)
                    result["fallback_used"] = True
                    result["fallback_profile"] = fallback_name
                    return result
                except Exception:
                    continue
            return {"success": False, "message": str(primary_err), "error": "llm_call_failed"}

    # --- Existing legacy path (unchanged) ---
    # Uses settings.llm.* when no routing_hint is provided
    model = model or settings.llm.model
    fallback_model = fallback_model or settings.llm.cheap_model
    max_tokens = max_tokens or settings.llm.max_tokens
    temperature = temperature or settings.llm.temperature
    api_key = api_key or settings.llm.api_key
    base_url = base_url or settings.llm.base_url
    # ... rest of existing call_llm() logic unchanged ...
```

Key design decisions:
- `routing_hint=None` (default) → uses the **existing legacy path** with `settings.llm.*`, zero behavior change for all current callers
- `routing_hint=RoutingHint(...)` → uses the **new routing path** with profile resolution
- The existing `_call_llm_api()` helper (lines 143-173) is reused as-is — it already accepts all needed params
- `_parse_response()` (lines 176-189) is reused as-is
- No new pseudo-code functions introduced

**`call_llm_stream()` changes** (currently at lines 23-69):

Add `routing_hint: Optional[RoutingHint] = None` parameter. When `routing_hint` is provided, resolve profile and use its `api_key`/`base_url`/`model` instead of `settings.llm.*`. The streaming logic (lines 54-69) remains identical.

**`call_llm_vision()` changes** (currently at lines 192-277):

Add `routing_hint: Optional[RoutingHint] = None` parameter. When `routing_hint` is provided, resolve profile. When `routing_hint` is `None`, try `RoutingHint(profile_name="vision")` first — if "vision" profile exists and is enabled, use it; otherwise fall back to the current `settings.llm.vision_model` / `settings.llm.model` logic.

### 3.7 Configuration Files

#### 3.7.1 `config/llm_profiles.yaml` (New)

```yaml
# LLM Profile Definitions
# Each profile is a complete, independent LLM configuration.
# Environment variable syntax: ${VAR_NAME} (resolved by load_yaml_config in settings.py)
# Note: the YAML loader only supports ${VAR_NAME}, NOT ${VAR_NAME:default} syntax.

profiles:
  strong:
    display_name: "GPT-4o (Strong Reasoning)"
    provider: openai
    api_key: ${LLM_STRONG_API_KEY}
    base_url: ${LLM_STRONG_BASE_URL}
    model: ${LLM_STRONG_MODEL}
    temperature: 0.3
    max_tokens: 8000
    top_p: 1.0
    frequency_penalty: 0.0
    presence_penalty: 0.0
    max_context_tokens: 128000
    cost_limit_per_call: 0.5
    is_default: false
    enabled: true

  fast:
    display_name: "DeepSeek V4 Flash (Fast & Cheap)"
    provider: deepseek
    api_key: ${LLM_FAST_API_KEY}
    base_url: ${LLM_FAST_BASE_URL}
    model: ${LLM_FAST_MODEL}
    temperature: 0.5
    max_tokens: 4096
    top_p: 1.0
    frequency_penalty: 0.0
    presence_penalty: 0.0
    max_context_tokens: 128000
    cost_limit_per_call: 0.1
    is_default: true
    enabled: true

  local:
    display_name: "Qwen 2.5 (Local)"
    provider: local
    api_key: ""
    base_url: ${LLM_LOCAL_BASE_URL}
    model: ${LLM_LOCAL_MODEL}
    temperature: 0.7
    max_tokens: 4096
    top_p: 1.0
    frequency_penalty: 0.0
    presence_penalty: 0.0
    max_context_tokens: 32000
    cost_limit_per_call: 0.0
    is_default: false
    enabled: false

  vision:
    display_name: "GPT-4o Vision"
    provider: openai
    api_key: ${LLM_VISION_API_KEY}
    base_url: ${LLM_VISION_BASE_URL}
    model: ${LLM_VISION_MODEL}
    temperature: 0.3
    max_tokens: 4096
    top_p: 1.0
    frequency_penalty: 0.0
    presence_penalty: 0.0
    max_context_tokens: 128000
    cost_limit_per_call: 0.0
    is_default: false
    enabled: true

# Default profile (used when no routing hint matches)
default_profile: fast

# Fallback chain: tried in order when the primary profile fails
fallback_chain:
  - strong
  - fast
  - local
```

**Note on env var syntax**: The current `load_yaml_config()` in `src/config/settings.py` (line 50-71) uses `re.sub(r'\$\{(\w+)\}', replace_env_var, content)` which only supports `${VAR_NAME}` syntax. It does NOT support default values like `${VAR:default}`. If an env var is not set, the literal `${VAR_NAME}` string remains in the config. The YAML loader code needs a small enhancement to support `${VAR_NAME:default_value}` syntax, OR the `llm_profiles.yaml` should only use `${VAR_NAME}` for required vars and hardcode defaults for optional ones.

**Required `.env` additions** (new env vars for multi-profile support):

```bash
# Strong profile (reasoning)
LLM_STRONG_API_KEY=
LLM_STRONG_BASE_URL=https://api.openai.com/v1
LLM_STRONG_MODEL=gpt-4o

# Fast profile (utility)
LLM_FAST_API_KEY=
LLM_FAST_BASE_URL=https://api.deepseek.com/v1
LLM_FAST_MODEL=deepseek-v4-flash

# Local profile
LLM_LOCAL_BASE_URL=http://localhost:11434/v1
LLM_LOCAL_MODEL=qwen2.5

# Vision profile (reuses existing env vars)
LLM_VISION_API_KEY=
LLM_VISION_BASE_URL=https://api.openai.com/v1
LLM_VISION_MODEL=gpt-4o
```

#### 3.7.2 `config/llm_routing.yaml` (New)

```yaml
# LLM Routing Rules
# Maps agents and actions to LLM profiles.

# Fixed agent → profile mapping
fixed_agents:
  requirement_analysis: strong
  report_generation: strong
  quality_check: strong
  data_collection: fast
  layout_design: fast
  cross_synthesis: strong
  persona_generation: fast
  result_calibration: fast
  simulated_response: fast
  survey_analysis: strong
  survey_integration: fast
  survey_optimization: fast
  # Report upgrade sub-agents
  chapter_writer: strong
  chapter_reviewer: strong
  global_reviewer: strong
  data_repair: fast
  structured_data_repair: fast

# Action/skill → profile mapping (for dynamic agents)
actions:
  llm_skill: strong
  analyze: strong
  analysis: strong
  generate: strong
  write: strong
  review: strong
  plan: strong
  synthesize: strong
  search: fast
  web_scraper: fast
  scrape: fast
  format: fast
  translate: fast
  extract: fast
  parse: fast
  classify: fast
  validate: fast
  check: fast
  embed: fast
  vision: vision
```

#### 3.7.3 `config/agents.yaml` (Modified)

The current `llm:` section in each agent config (e.g., `llm: {model: gpt-4o, temperature: 0.3, max_tokens: 2000}`) is dead code — `AgentLLMConfig` is loaded but never consumed at runtime. Replace with a `llm_profile` reference:

```yaml
requirement_analysis:
  llm_profile: strong          # Reference to llm_profiles.yaml profile
  # The old llm: {model, temperature, max_tokens} section is removed
  capabilities:
    - Industry Identification
    ...
```

This keeps `agents.yaml` as the source of truth for agent capabilities while delegating LLM config to the profile system. The `AgentLLMConfig` dataclass in `src/config/agents.py` will be updated to carry a `profile_name: str` field instead of `model/temperature/max_tokens`.

### 3.8 Persistence: `data/llm_profiles.json`

Replace the current single `data/llm_config.json` with a multi-profile file:

```json
{
  "version": 2,
  "profiles": {
    "strong": {
      "name": "strong",
      "display_name": "GPT-4o (Strong Reasoning)",
      "provider": "openai",
      "api_key": "sk-...",
      "base_url": "https://api.openai.com/v1",
      "model": "gpt-4o",
      "temperature": 0.3,
      "max_tokens": 8000,
      "top_p": 1.0,
      "frequency_penalty": 0.0,
      "presence_penalty": 0.0,
      "max_context_tokens": 128000,
      "cost_limit_per_call": 0.5,
      "is_default": false,
      "enabled": true,
      "created_at": "2026-07-01T10:00:00Z",
      "updated_at": "2026-07-01T10:00:00Z"
    },
    "fast": { ... },
    "local": { ... }
  },
  "default_profile": "fast",
  "fallback_chain": ["strong", "fast", "local"],
  "routing": {
    "fixed_agents": { "requirement_analysis": "strong", ... },
    "actions": { "llm_skill": "strong", ... }
  }
}
```

**Loading priority** (same as current, but for profiles):
1. `LLMProfile` dataclass defaults
2. Environment variables (per-profile env vars like `LLM_STRONG_API_KEY`)
3. `config/llm_profiles.yaml` + `config/llm_routing.yaml`
4. `data/llm_profiles.json` (highest — survives restart, set by frontend)

**Migration**: On first startup, if `data/llm_config.json` exists (old format) but `data/llm_profiles.json` doesn't, auto-migrate the old config into a profile named `"migrated"`. This profile is set as `is_default: true` and the `default_profile` is set to `"migrated"`. The migration reads the old JSON fields using the same mapping as `_load_llm_config_from_disk()` (e.g., `"api_endpoint"` → `base_url`).

### 3.9 Settings Class Changes

The `Settings` class in `src/config/settings.py` is extended, not replaced. The existing `self.llm = LLMConfig()` is kept for backward compatibility (it will be a read-only view of the default profile).

```python
# src/config/settings.py (modified)

from src.config.llm_profiles import LLMProfile, LLMProfileRegistry

class Settings:
    def __init__(self, config_path=None):
        ...
        # New: multi-profile registry
        self.llm_profiles = LLMProfileRegistry()
        # Keep for backward compat (deprecated, derived from default profile)
        self.llm = LLMConfig()
        ...
        # In _load_config(), after existing loading:
        self._load_llm_profiles_from_yaml()
        self._load_llm_profiles_from_disk()
        self._migrate_legacy_llm_config()
        self._sync_llm_config_from_profiles()  # Keep self.llm in sync
    
    def get_profile(self, name: str) -> Optional[LLMProfile]:
        """Get a specific LLM profile."""
        return self.llm_profiles.profiles.get(name)
    
    def get_default_profile(self) -> Optional[LLMProfile]:
        """Get the default LLM profile."""
        return self.llm_profiles.profiles.get(self.llm_profiles.default_profile)
    
    def update_profile(self, name: str, config: Dict[str, Any]) -> LLMProfile:
        """Update or create a profile. Does NOT affect other profiles."""
        if name in self.llm_profiles.profiles:
            profile = self.llm_profiles.profiles[name]
            for key, value in config.items():
                if key == "api_endpoint":
                    setattr(profile, "base_url", value)
                elif hasattr(profile, key):
                    setattr(profile, key, value)
            from datetime import datetime, timezone
            profile.updated_at = datetime.now(timezone.utc).isoformat()
        else:
            profile = LLMProfile(name=name)
            for key, value in config.items():
                if key == "api_endpoint":
                    profile.base_url = value
                elif key == "display_name":
                    profile.display_name = value
                elif hasattr(profile, key):
                    setattr(profile, key, value)
            from datetime import datetime, timezone
            profile.created_at = datetime.now(timezone.utc).isoformat()
            profile.updated_at = profile.created_at
            self.llm_profiles.profiles[name] = profile
        self._persist_llm_profiles()
        self._sync_llm_config_from_profiles()
        return profile
    
    def delete_profile(self, name: str) -> bool:
        """Delete a profile. Cannot delete the default profile."""
        if name == self.llm_profiles.default_profile:
            return False
        if name not in self.llm_profiles.profiles:
            return False
        del self.llm_profiles.profiles[name]
        self._persist_llm_profiles()
        return True
    
    def set_default_profile(self, name: str) -> None:
        """Change the default profile."""
        if name not in self.llm_profiles.profiles:
            raise ValueError(f"Profile '{name}' does not exist")
        for p in self.llm_profiles.profiles.values():
            p.is_default = (p.name == name)
        self.llm_profiles.default_profile = name
        self._persist_llm_profiles()
        self._sync_llm_config_from_profiles()
    
    def update_routing(self, routing_config: Dict[str, Any]) -> None:
        """Update routing rules."""
        if "default_profile" in routing_config:
            self.llm_profiles.default_profile = routing_config["default_profile"]
        if "fallback_chain" in routing_config:
            self.llm_profiles.fallback_chain = routing_config["fallback_chain"]
        if "fixed_agent_routing" in routing_config:
            self.llm_profiles.fixed_agent_routing = routing_config["fixed_agent_routing"]
        if "action_routing" in routing_config:
            self.llm_profiles.action_routing = routing_config["action_routing"]
        self._persist_llm_profiles()
    
    def _persist_llm_profiles(self) -> None:
        """Persist all profiles to data/llm_profiles.json."""
        try:
            path = Path("data/llm_profiles.json")
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "version": 2,
                "profiles": {},
                "default_profile": self.llm_profiles.default_profile,
                "fallback_chain": self.llm_profiles.fallback_chain,
                "routing": {
                    "fixed_agents": self.llm_profiles.fixed_agent_routing,
                    "actions": self.llm_profiles.action_routing,
                },
            }
            for name, profile in self.llm_profiles.profiles.items():
                data["profiles"][name] = {
                    "name": profile.name,
                    "display_name": profile.display_name,
                    "provider": profile.provider,
                    "api_key": profile.api_key,
                    "base_url": profile.base_url,
                    "model": profile.model,
                    "temperature": profile.temperature,
                    "max_tokens": profile.max_tokens,
                    "top_p": profile.top_p,
                    "frequency_penalty": profile.frequency_penalty,
                    "presence_penalty": profile.presence_penalty,
                    "max_context_tokens": profile.max_context_tokens,
                    "cost_limit_per_call": profile.cost_limit_per_call,
                    "is_default": profile.is_default,
                    "enabled": profile.enabled,
                    "created_at": profile.created_at,
                    "updated_at": profile.updated_at,
                }
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to persist LLM profiles: %s", e)
    
    def _load_llm_profiles_from_disk(self) -> None:
        """Load profiles from data/llm_profiles.json (highest priority)."""
        path = Path("data/llm_profiles.json")
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("version") != 2:
                return
            self.llm_profiles.default_profile = data.get("default_profile", self.llm_profiles.default_profile)
            self.llm_profiles.fallback_chain = data.get("fallback_chain", self.llm_profiles.fallback_chain)
            routing = data.get("routing", {})
            self.llm_profiles.fixed_agent_routing = routing.get("fixed_agents", {})
            self.llm_profiles.action_routing = routing.get("actions", {})
            for name, pdata in data.get("profiles", {}).items():
                profile = LLMProfile(
                    name=pdata.get("name", name),
                    display_name=pdata.get("display_name", ""),
                    provider=pdata.get("provider", "openai"),
                    api_key=pdata.get("api_key", ""),
                    base_url=pdata.get("base_url", "https://api.openai.com/v1"),
                    model=pdata.get("model", "gpt-4o"),
                    temperature=float(pdata.get("temperature", 0.7)),
                    max_tokens=int(pdata.get("max_tokens", 4096)),
                    top_p=float(pdata.get("top_p", 1.0)),
                    frequency_penalty=float(pdata.get("frequency_penalty", 0.0)),
                    presence_penalty=float(pdata.get("presence_penalty", 0.0)),
                    max_context_tokens=int(pdata.get("max_context_tokens", 128000)),
                    cost_limit_per_call=float(pdata.get("cost_limit_per_call", 0.0)),
                    is_default=pdata.get("is_default", False),
                    enabled=pdata.get("enabled", True),
                    created_at=pdata.get("created_at", ""),
                    updated_at=pdata.get("updated_at", ""),
                )
                self.llm_profiles.profiles[name] = profile
        except Exception as e:
            logger.warning("Failed to load persisted LLM profiles: %s", e)
    
    def _load_llm_profiles_from_yaml(self) -> None:
        """Load profiles from config/llm_profiles.yaml and config/llm_routing.yaml."""
        profiles_path = "config/llm_profiles.yaml"
        if os.path.exists(profiles_path):
            try:
                config = load_yaml_config(profiles_path)
                for name, pdata in config.get("profiles", {}).items():
                    profile = LLMProfile(name=name)
                    profile.display_name = pdata.get("display_name", "")
                    profile.provider = pdata.get("provider", "openai")
                    profile.api_key = pdata.get("api_key", "")
                    profile.base_url = pdata.get("base_url", "https://api.openai.com/v1")
                    profile.model = pdata.get("model", "gpt-4o")
                    profile.temperature = float(pdata.get("temperature", 0.7))
                    profile.max_tokens = int(pdata.get("max_tokens", 4096))
                    profile.top_p = float(pdata.get("top_p", 1.0))
                    profile.frequency_penalty = float(pdata.get("frequency_penalty", 0.0))
                    profile.presence_penalty = float(pdata.get("presence_penalty", 0.0))
                    profile.max_context_tokens = int(pdata.get("max_context_tokens", 128000))
                    profile.cost_limit_per_call = float(pdata.get("cost_limit_per_call", 0.0))
                    profile.is_default = pdata.get("is_default", False)
                    profile.enabled = pdata.get("enabled", True)
                    self.llm_profiles.profiles[name] = profile
                self.llm_profiles.default_profile = config.get("default_profile", "fast")
                self.llm_profiles.fallback_chain = config.get("fallback_chain", ["strong", "fast", "local"])
            except Exception as e:
                logger.warning("Failed to load llm_profiles.yaml: %s", e)
        
        routing_path = "config/llm_routing.yaml"
        if os.path.exists(routing_path):
            try:
                routing = load_yaml_config(routing_path)
                self.llm_profiles.fixed_agent_routing = routing.get("fixed_agents", {})
                self.llm_profiles.action_routing = routing.get("actions", {})
            except Exception as e:
                logger.warning("Failed to load llm_routing.yaml: %s", e)
    
    def _migrate_legacy_llm_config(self) -> None:
        """Migrate old data/llm_config.json to new format."""
        old_path = Path("data/llm_config.json")
        new_path = Path("data/llm_profiles.json")
        if old_path.exists() and not new_path.exists():
            try:
                data = json.loads(old_path.read_text(encoding="utf-8"))
                profile = LLMProfile(
                    name="migrated",
                    display_name="Migrated Config",
                    provider=data.get("provider", "openai"),
                    api_key=data.get("api_key", ""),
                    base_url=data.get("api_endpoint", data.get("base_url", "https://api.openai.com/v1")),
                    model=data.get("model", "gpt-4o"),
                    temperature=float(data.get("temperature", 0.7)),
                    max_tokens=int(data.get("max_tokens", 4096)),
                    top_p=float(data.get("top_p", 1.0)),
                    frequency_penalty=float(data.get("frequency_penalty", 0.0)),
                    presence_penalty=float(data.get("presence_penalty", 0.0)),
                    is_default=True,
                    enabled=True,
                )
                from datetime import datetime, timezone
                profile.created_at = datetime.now(timezone.utc).isoformat()
                profile.updated_at = profile.created_at
                self.llm_profiles.profiles["migrated"] = profile
                self.llm_profiles.default_profile = "migrated"
                self._persist_llm_profiles()
                logger.info("Migrated legacy llm_config.json to llm_profiles.json")
            except Exception as e:
                logger.warning("Failed to migrate legacy LLM config: %s", e)
    
    def _sync_llm_config_from_profiles(self) -> None:
        """Keep self.llm (LLMConfig) in sync with the default profile for backward compat."""
        profile = self.get_default_profile()
        if profile:
            self.llm.provider = profile.provider
            self.llm.api_key = profile.api_key
            self.llm.base_url = profile.base_url
            self.llm.model = profile.model
            self.llm.temperature = profile.temperature
            self.llm.max_tokens = profile.max_tokens
            self.llm.top_p = profile.top_p
            self.llm.frequency_penalty = profile.frequency_penalty
            self.llm.presence_penalty = profile.presence_penalty
```

### 3.10 Backward Compatibility

The old `call_llm()` signature is fully preserved. When `routing_hint` is not provided (the default), the function uses the existing `settings.llm.*` path — zero behavior change for all current callers.

```python
# Old code still works (routing_hint defaults to None):
result = await call_llm(prompt, model="gpt-4o", api_key="sk-...", base_url="https://...")

# New code with routing:
result = await call_llm(prompt, routing_hint=RoutingHint(agent_type="quality_check"))
result = await call_llm(prompt, routing_hint=RoutingHint(action="analyze"))
result = await call_llm(prompt, routing_hint=RoutingHint(profile_name="strong"))
```

The `settings.llm` attribute is kept as a read-only view of the default profile, synchronized via `_sync_llm_config_from_profiles()`. All existing code that reads `settings.llm.model`, `settings.llm.api_key`, etc. continues to work.

### 3.11 Migration of Existing Call Sites

| Current Pattern | File(s) | Migration Path |
|---|---|---|
| `call_llm(prompt, model=..., api_key=..., base_url=...)` | `generic_agent.py`, `report_upgrade/*.py` | Add `routing_hint=RoutingHint(agent_type=...)` or `RoutingHint(action=...)`, remove explicit model/api_key/base_url |
| `LLMSkill()` then `.execute(prompt)` | `research_api.py`, `task_structure.py`, `semantic_intent.py`, `revision_intent_analyzer.py`, `translate_operation.py`, `findings.py`, `batch_revision_service.py` | Replace with `call_llm(prompt, routing_hint=...)`. LLMSkill will be deprecated. |
| `GenericAgent._call_llm_directly()` creating `AsyncOpenAI` directly | `generic_agent.py` line 4302 | Replace with `call_llm(prompt, routing_hint=RoutingHint(action=self._current_action))` |
| Direct `AsyncOpenAI` in `layer3_depth.py` | `layer3_depth.py` line 208 | Replace with `call_llm(prompt, routing_hint=RoutingHint(agent_type="quality_check"))` |
| Direct `AsyncOpenAI` in `llm_judge.py` | `llm_judge.py` line 70 | Replace with `call_llm(prompt, routing_hint=RoutingHint(agent_type="quality_judge"))` |
| `layer2_methodology.py` with injected `llm_client` | `layer2_methodology.py` line 65 | Inject `None` (or remove injection), let it use `call_llm()` with routing hint internally |
| `settings.llm.model` / `settings.llm.api_key` | Multiple files | Replace with `settings.get_default_profile().model` or `settings.get_profile("strong").api_key`. The `settings.llm` stays in sync via `_sync_llm_config_from_profiles()` as a transitional measure. |

### 3.12 Session-Scoped Config (Fix Per-Request Overwrite)

Currently, research API endpoints (`/api/v1/research/start`, `/api/v1/research/quick-start`, `/api/v1/research/interact`) accept 9 LLM form fields (`llm_provider`, `llm_model`, `llm_api_key`, `llm_api_endpoint`, `llm_temperature`, `llm_max_tokens`, `llm_top_p`, `llm_frequency_penalty`, `llm_presence_penalty`) and call `settings.update_from_request()`, which permanently modifies the global singleton. Fix:

**Backend change** — in `src/api/main.py`:

```python
@router.post("/api/v1/research/start")
async def start_research(
    ...,
    llm_profile: Optional[str] = Form(None),      # NEW: select a profile by name
    llm_provider: Optional[str] = Form(None),       # KEPT for backward compat
    llm_model: Optional[str] = Form(None),
    llm_api_key: Optional[str] = Form(None),
    llm_api_endpoint: Optional[str] = Form(None),
    llm_temperature: Optional[float] = Form(None),
    llm_max_tokens: Optional[int] = Form(None),
    llm_top_p: Optional[float] = Form(None),
    llm_frequency_penalty: Optional[float] = Form(None),
    llm_presence_penalty: Optional[float] = Form(None),
    ...
):
    # Build session routing hint — does NOT mutate global settings
    session_routing_hint = None
    if llm_profile:
        session_routing_hint = RoutingHint(profile_name=llm_profile, force_profile=True)
    # Legacy: if old-style LLM fields are provided, do NOT call settings.update_from_request()
    # Instead, pass them through as explicit overrides in call_llm() calls within this session
    
    # Pass session_routing_hint to the research API method
    result = await research_api.start_research(
        ...,
        routing_hint=session_routing_hint,
        legacy_llm_config=legacy_config if not llm_profile else None,
    )
```

**How routing_hint propagates**: The `ResearchOrchestrator` (in `src/core/orchestrator/orchestrator.py`) does NOT currently accept a `routing_hint` parameter. It has `routing_adapter` and `use_intelligent_routing` parameters instead. The routing hint will be stored on the orchestrator instance and passed to agents when they call `call_llm()`:

```python
class ResearchOrchestrator:
    def __init__(self, ..., routing_hint: Optional[RoutingHint] = None):
        self._session_routing_hint = routing_hint
        ...
    
    # When creating agents or making LLM calls, pass the hint:
    # result = await call_llm(prompt, routing_hint=self._session_routing_hint)
```

**No global state mutation.** The `settings.update_from_request()` call is removed from all research endpoints.

---

## 4. Frontend Design

### 4.1 Multi-Profile Settings Page

Replace the current single LLM config form with a **profile list + detail editor**:

```
┌─────────────────────────────────────────────────────────────┐
│  LLM Configuration                                          │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Profiles                              [+ Add New]  │    │
│  │                                                     │    │
│  │  ┌──────────────────┐  ┌──────────────────┐        │    │
│  │  │ ⭐ GPT-4o        │  │   DeepSeek V4     │        │    │
│  │  │ Strong Reasoning  │  │   Fast & Cheap    │        │    │
│  │  │ Default: ✓        │  │   Default: ●      │        │    │
│  │  │ Enabled: ✓        │  │   Enabled: ✓      │        │    │
│  │  └──────────────────┘  └──────────────────┘        │    │
│  │                                                     │    │
│  │  ┌──────────────────┐  ┌──────────────────┐        │    │
│  │  │   Qwen 2.5       │  │   GPT-4o Vision   │        │    │
│  │  │   Local           │  │   Vision           │        │    │
│  │  │   Default: ●      │  │   Default: ●      │        │    │
│  │  │   Enabled: ○      │  │   Enabled: ✓      │        │    │
│  │  └──────────────────┘  └──────────────────┘        │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Profile Detail: GPT-4o (Strong Reasoning)    [Del] │    │
│  │                                                     │    │
│  │  Profile Name:  [strong          ]                  │    │
│  │  Display Name:  [GPT-4o (Strong Reasoning)]         │    │
│  │  Provider:      [OpenAI       ▼]                    │    │
│  │  API Endpoint:  [https://api.openai.com/v1]         │    │
│  │  API Key:       [sk-...        👁]                  │    │
│  │  Model:         [gpt-4o       ▼]                    │    │
│  │                                                     │    │
│  │  Temperature:   ──●────── 0.3                       │    │
│  │  Max Tokens:    [8000     ]                         │    │
│  │  Top P:         ─────●── 1.0                        │    │
│  │  Freq Penalty:  ──●────── 0.0                       │    │
│  │  Pres Penalty:  ──●────── 0.0                       │    │
│  │                                                     │    │
│  │  ☑ Enabled    ○ Set as Default                      │    │
│  │                                                     │    │
│  │                              [Save Profile]          │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Routing Rules                                       │    │
│  │                                                     │    │
│  │  Default Profile:  [fast       ▼]                   │    │
│  │  Fallback Chain:   strong → fast → local            │    │
│  │                    [Edit Chain]                      │    │
│  │                                                     │    │
│  │  Agent Routing:                                      │    │
│  │    requirement_analysis → [strong ▼]                 │    │
│  │    report_generation    → [strong ▼]                 │    │
│  │    quality_check        → [strong ▼]                 │    │
│  │    data_collection      → [fast   ▼]                 │    │
│  │    ...                                              │    │
│  │                                                     │    │
│  │  Action Routing:                                     │    │
│  │    analyze  → [strong ▼]                             │    │
│  │    search   → [fast   ▼]                             │    │
│  │    vision   → [vision ▼]                             │    │
│  │    ...                                              │    │
│  │                                                     │    │
│  │  ☑ Auto-classify unknown actions by keyword          │    │
│  │                                                     │    │
│  │                              [Save Routing]          │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Frontend Data Model Changes

```typescript
// web/src/types/settings.ts (modified)

export interface LLMProfile {
  name: string;
  displayName: string;
  provider: LLMProvider;
  apiKey: string;
  apiEndpoint: string;
  model: string;
  temperature: number;
  maxTokens: number;
  topP: number;
  frequencyPenalty: number;
  presencePenalty: number;
  maxContextTokens: number;
  costLimitPerCall: number;
  isDefault: boolean;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface LLMRoutingConfig {
  defaultProfile: string;
  fallbackChain: string[];
  fixedAgentRouting: Record<string, string>;   // agent_type → profile_name
  actionRouting: Record<string, string>;        // action → profile_name
  autoClassify: boolean;                        // keyword auto-classification
}

// Replace: llm: LLMConfig
// With:
export interface LLMProfilesState {
  profiles: Record<string, LLMProfile>;
  routing: LLMRoutingConfig;
  activeProfileName: string | null;   // Currently editing
}
```

### 4.3 Frontend Store Changes

```typescript
// web/src/store/useSettingsStore.ts (modified)

interface SettingsState {
  // Replace: llm: LLMConfig; savedLlm: LLMConfig;
  // With:
  llmProfiles: LLMProfilesState;
  savedLlmProfiles: LLMProfilesState;
  
  // Keep for backward compat during migration
  llm: LLMConfig;  // Deprecated, derived from default profile
  ...
}

interface SettingsMethods {
  // Profile CRUD
  createProfile: (profile: LLMProfile) => Promise<void>;
  updateProfile: (name: string, updates: Partial<LLMProfile>) => Promise<void>;
  deleteProfile: (name: string) => Promise<void>;
  setDefaultProfile: (name: string) => Promise<void>;
  toggleProfileEnabled: (name: string) => Promise<void>;
  
  // Routing
  updateRouting: (routing: Partial<LLMRoutingConfig>) => Promise<void>;
  
  // Replace: persistLLMConfig()
  persistProfiles: () => Promise<void>;
  
  // Backward compat
  persistLLMConfig: () => Promise<void>;  // Deprecated
}
```

### 4.4 Frontend Persistence

**localStorage** stores the full `LLMProfilesState` (all profiles + routing config) under the same key `Zensers-settings-v2`. Each profile's API key is stored separately for security:

```typescript
// localStorage structure:
{
  state: {
    llmProfiles: {
      profiles: {
        "strong": { ...profile without apiKey },
        "fast": { ...profile without apiKey },
      },
      routing: { ... },
      activeProfileName: "strong",
    },
    // API keys stored separately per profile
    _llmApiKeys: {
      "strong": "sk-...",
      "fast": "sk-...",
    },
    ...
  },
  version: 1,  // Bumped from 0 to trigger migration
}
```

**Backend disk** (`data/llm_profiles.json`) stores everything including API keys (server-side only, not exposed to frontend in GET responses).

### 4.5 Frontend API Endpoints

Replace the single-config endpoints with multi-profile endpoints:

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/llm/profiles` | List all profiles (API keys redacted) |
| GET | `/api/v1/llm/profiles/{name}` | Get single profile (API key redacted) |
| POST | `/api/v1/llm/profiles` | Create new profile |
| PUT | `/api/v1/llm/profiles/{name}` | Update profile (only sent fields are changed) |
| DELETE | `/api/v1/llm/profiles/{name}` | Delete profile (cannot delete default) |
| POST | `/api/v1/llm/profiles/{name}/default` | Set as default profile |
| POST | `/api/v1/llm/profiles/{name}/toggle` | Enable/disable profile |
| GET | `/api/v1/llm/routing` | Get routing config |
| PUT | `/api/v1/llm/routing` | Update routing config |
| POST | `/api/v1/llm/profiles/test/{name}` | Test connectivity for a profile |
| GET | `/api/v1/llm/config` | **Deprecated** — returns default profile for backward compat |
| POST | `/api/v1/llm/config` | **Deprecated** — updates default profile for backward compat |
| POST | `/api/v1/llm/config/reset` | **Deprecated** — resets all profiles to env defaults |

**Key: saving one profile does NOT affect other profiles.** Each profile is independently persisted.

### 4.6 Research Page LLM Selection

The current chat page (`web/src/components/chat/ChatInput.tsx`) shows a compact provider + model dropdown in the toolbar. When a research is started, the frontend reads the full LLM config from `useSettingsStore().llm` (populated from the Settings page) and sends it as FormData fields via `web/src/lib/api.ts`.

**Change**: Replace the provider + model dropdown with a profile selector:

```
┌─────────────────────────────────────┐
│  LLM Profile:  [fast (Default) ▼]   │
│                                     │
│  ℹ Using "DeepSeek V4 Flash"       │
│    Model: deepseek-v4-flash         │
│    Provider: DeepSeek               │
│                                     │
│  [⚙ Manage Profiles]               │
└─────────────────────────────────────┘
```

**Frontend API change**: In `web/src/lib/api.ts`, the `startResearch()`, `quickStart()`, `sendChatMessage()`, and `clickSuggestion()` methods currently append 9 LLM fields (`llm_provider`, `llm_model`, `llm_api_key`, etc.) to FormData. Replace with a single `llm_profile` field:

```typescript
// Before:
formData.append('llm_provider', llmConfig.provider);
formData.append('llm_model', llmConfig.model);
// ... 7 more fields

// After:
formData.append('llm_profile', selectedProfileName);
```

The backend resolves the profile name to the full LLM config server-side, so API keys never need to be sent from the frontend. This also eliminates the current security issue where API keys are transmitted with every research request.

---

## 5. Migration Strategy

### 5.1 Phase 1: Backend Infrastructure (No Frontend Changes)

1. Create `LLMProfile`, `LLMProfileRegistry`, `RoutingHint`, `LLMRouter`, `LLMClientPool`
2. Create `config/llm_profiles.yaml` and `config/llm_routing.yaml` with initial profiles derived from current `.env`
3. Modify `call_llm()` to accept `routing_hint` while keeping full backward compat
4. Add `init_llm_infrastructure()` to app startup
5. Add auto-migration from `data/llm_config.json` to `data/llm_profiles.json`
6. Keep `settings.llm` as a read-only view of the default profile (backward compat)
7. Add new API endpoints alongside old ones

### 5.2 Phase 2: Migrate Call Sites

1. Update `GenericAgent` to pass `RoutingHint(action=...)` when calling `call_llm()`, and replace `_call_llm_directly()` (line 4302) with `call_llm()` + routing hint
2. Update `FixedAgent` subclasses in `report_upgrade/` to pass `RoutingHint(agent_type=...)` 
3. Replace direct `AsyncOpenAI` in `layer3_depth.py` (line 208) with `call_llm()` + `RoutingHint(agent_type="quality_check")`
4. Replace direct `AsyncOpenAI` in `llm_judge.py` (line 70) with `call_llm()` + `RoutingHint(agent_type="quality_judge")`
5. Replace `LLMSkill()` instantiation in `research_api.py`, `task_structure.py`, `semantic_intent.py`, `revision_intent_analyzer.py`, `translate_operation.py`, `findings.py`, `batch_revision_service.py` with `call_llm()` + routing hints
6. Fix research API in `src/api/main.py` to use session-scoped routing instead of `settings.update_from_request()`
7. Add `routing_hint` parameter to `ResearchOrchestrator.__init__()` and propagate to agents

### 5.3 Phase 3: Frontend Multi-Profile UI

1. Create `LLMProfileCard`, `LLMProfileEditor`, `LLMRoutingEditor` components
2. Update `LLMConfigPanel` to use profile list + detail layout
3. Update Zustand store with profile CRUD methods
4. Update research page to use profile selector
5. Add localStorage migration (version 0 → 1)

### 5.4 Phase 4: Cleanup

1. Remove deprecated `settings.llm` direct access (replace with `settings.get_default_profile()`)
2. Remove deprecated API endpoints (`/api/v1/llm/config`, `/api/v1/llm/config/reset`)
3. Deprecate `LLMSkill` — after all consumers are migrated to `call_llm()` + routing hints, mark `LLMSkill` as deprecated. Keep it registered in the skill registry for any external consumers, but add a deprecation warning in its `execute()` method.
4. Remove `AgentLLMConfig` from `src/config/agents.py` (replaced by `llm_profile` reference in `agents.yaml`)
5. Remove `settings._persist_llm_config()` and `settings._load_llm_config_from_disk()` (replaced by profile-based persistence)
6. Remove `data/llm_config.json` after migration is confirmed

---

## 6. Error Handling

### 6.1 Profile Not Found

If `routing_hint.profile_name` references a non-existent or disabled profile:
- Log warning: `Profile "xyz" not found or disabled, falling back to default`
- Use default profile

### 6.2 All Profiles Failed

If the entire fallback chain fails:
- Return `{"success": False, "error": "all_profiles_failed", "message": "All LLM profiles in fallback chain failed"}`
- Log error with details of each attempt

### 6.3 No Enabled Profiles

If no profiles are enabled at all:
- `LLMRouter.resolve()` raises `RuntimeError("No enabled LLM profile available")`
- `call_llm()` catches this and returns `{"success": False, "error": "no_profile_available"}`

### 6.4 Circular Fallback

The fallback chain is a flat list, not recursive. If profile A fails and falls back to B, and B also fails, it tries C — not back to A. No circular risk.

### 6.5 Config Validation

On profile save:
- `name` must be non-empty, alphanumeric + underscore, max 32 chars
- `provider` must be one of: `openai`, `deepseek`, `local`, `custom`
- `base_url` must be a valid URL (or empty for local)
- `model` must be non-empty
- `temperature` must be 0-2
- `max_tokens` must be 100-128000
- Cannot delete the default profile (must set another as default first)
- Cannot disable the default profile

---

## 7. Testing Strategy

### 7.1 Unit Tests

- `LLMRouter.resolve()` — test all 5 priority levels, edge cases (missing profile, disabled profile, no hint)
- `LLMProfileRegistry` — CRUD operations, validation, migration
- `LLMClientPool` — client caching, invalidation
- `call_llm()` with routing hints — mock router, verify correct profile selected
- Backward compat — old `call_llm(prompt, api_key=..., base_url=...)` still works

### 7.2 Integration Tests

- Full routing flow: agent → router → profile → client → API call
- Fallback chain: primary fails → fallback succeeds
- Profile CRUD via API endpoints
- Frontend ↔ backend profile sync

### 7.3 Migration Tests

- Old `data/llm_config.json` → new `data/llm_profiles.json` auto-migration
- Old `call_llm()` calls still work after migration
- Old frontend localStorage → new format migration

---

## 8. Security Considerations

1. **API key isolation**: Each profile's API key is stored independently. Deleting a profile removes its key. Updating one profile's key does not affect others.

2. **API key redaction**: `GET /api/v1/llm/profiles` returns `hasApiKey: true/false` instead of the actual key. `GET /api/v1/llm/profiles/{name}` returns the API key only for the editing form (matching current behavior where `GET /api/v1/llm/config` returns the unredacted key). In a future iteration, even the single-profile GET should redact the key and only accept it on POST/PUT.

3. **No cross-session leakage**: Session-scoped routing hints are not persisted. One user's profile selection does not affect another user's session.

4. **Default profile protection**: Cannot delete or disable the default profile, ensuring the system always has a working LLM config.

5. **Cost limits per profile**: Each profile has its own `cost_limit_per_call`, preventing a misconfigured cheap profile from accidentally running expensive operations.
