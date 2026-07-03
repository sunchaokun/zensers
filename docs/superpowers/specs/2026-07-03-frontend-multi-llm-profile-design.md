# Phase 3: Frontend Multi-LLM Profile UI Design

**Date:** 2026-07-03
**Status:** Draft

## Goal

Migrate the frontend from a single flat LLM config form to a multi-profile management UI, fully wired to the backend `/api/v1/llm/profiles/*` and `/api/v1/llm/routing` endpoints.

## Design Decisions

1. **Layout**: Left sidebar profile list + right panel parameter form (VSCode Settings style)
2. **Routing config**: Collapsible section inside the profile panel, not a separate tab
3. **API migration**: Complete migration to `/profiles` endpoints; remove all `/llm/config` calls
4. **Backward compat**: The `POST /api/v1/llm/config` legacy endpoint remains on backend for any external callers, but frontend no longer uses it

## Architecture

### Data Flow

```
User edits profile in UI
  → useSettingsStore.updateProfile(name, fields)
    → api.updateLLMProfile(name, fields)
      → PUT /api/v1/llm/profiles/{name}
    → store.profiles[name] updated locally
    → if name === activeProfile, update store.llm from profile fields
```

### Type Changes (`settings.ts`)

New types mirroring backend dataclasses:

```typescript
interface LLMProfile {
  name: string;
  display_name: string;
  provider: string;
  api_key: string;
  base_url: string;
  model: string;
  fallback_model: string;
  temperature: number;
  max_tokens: number;
  top_p: number;
  frequency_penalty: number;
  presence_penalty: number;
  max_context_tokens: number;
  cost_limit_per_call: number;
  is_default: boolean;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

interface LLMProfileRegistry {
  profiles: Record<string, LLMProfile>;
  default_profile: string;
  fallback_chain: string[];
  fixed_agent_routing: Record<string, string>;
  action_routing: Record<string, string>;
}
```

The existing `LLMConfig` type is replaced. `AppSettings` holds:
- `profiles: Record<string, LLMProfile>` — all profiles
- `activeProfileName: string` — currently selected profile in the UI
- `defaultProfileName: string` — which profile is default
- `routingConfig: { fixed_agent_routing, action_routing, fallback_chain }`

Helper `activeProfile` getter derives the selected `LLMProfile` from `profiles[activeProfileName]`.

### Store Changes (`useSettingsStore.ts`)

New state:
- `profiles: Record<string, LLMProfile>` — replaces `llm`/`savedLlm`
- `activeProfileName: string`
- `defaultProfileName: string`
- `routingConfig: { fixed_agent_routing, action_routing, fallback_chain }`

New actions:
- `loadProfiles()` → `GET /api/v1/llm/profiles` → populate `profiles`, `defaultProfileName`, `routingConfig`
- `createProfile(data)` → `POST /api/v1/llm/profiles`
- `updateProfile(name, fields)` → `PUT /api/v1/llm/profiles/{name}`
- `deleteProfile(name)` → `DELETE /api/v1/llm/profiles/{name}`
- `setDefaultProfile(name)` → `POST /api/v1/llm/profiles/{name}/default`
- `switchProfile(name)` → sets `activeProfileName`
- `updateRouting(config)` → `PUT /api/v1/llm/routing`

Removed:
- `persistLLMConfig()` — replaced by `updateProfile()`
- `syncConfigToBackend()` — replaced by `loadProfiles()`
- `llm` / `savedLlm` state — replaced by `profiles[activeProfileName]`

Compatibility:
- `llm` getter remains as a computed property that returns `profiles[activeProfileName]` mapped to the old `LLMConfig` shape. This ensures other components that read `settings.llm.model` etc. continue to work without changes.

### API Client Changes (`api.ts`)

New methods:
- `getLLMProfiles()` → `GET /api/v1/llm/profiles`
- `getLLMProfile(name)` → `GET /api/v1/llm/profiles/{name}`
- `createLLMProfile(data)` → `POST /api/v1/llm/profiles`
- `updateLLMProfile(name, data)` → `PUT /api/v1/llm/profiles/{name}`
- `deleteLLMProfile(name)` → `DELETE /api/v1/llm/profiles/{name}`
- `setDefaultLLMProfile(name)` → `POST /api/v1/llm/profiles/{name}/default`
- `getLLMRouting()` → `GET /api/v1/llm/routing`
- `updateLLMRouting(data)` → `PUT /api/v1/llm/routing`

Removed:
- All calls to `POST /api/v1/llm/config` and `GET /api/v1/llm/config`

### UI Changes (`LLMConfigPanel.tsx`)

**Layout:**

```
┌─────────────────────────────────────────────────────┐
│ LLM 配置                                    [Reset] │
├──────────────┬──────────────────────────────────────┤
│ Profiles     │ Profile: strong              [⭐]    │
│              │                                      │
│ ⭐ strong    │ Provider    [OpenAI      ▼]          │
│   fast       │ API Endpoint [https://...     ]      │
│   local      │ API Key     [••••••••        ] 👁     │
│              │ Model       [gpt-4o          ▼]      │
│ ───────────  │ Temperature ────●──── 0.7            │
│ [+ New]      │ Max Tokens  [4096                    │
│              │ Top P       ────●──── 1.0            │
│              │ Freq Penalty────●──── 0.0            │
│              │ Pres Penalty────●──── 0.0            │
│              │                                      │
│              │ ▶ 路由规则                           │
│              │   (collapsible routing config)        │
└──────────────┴──────────────────────────────────────┘
```

**Left sidebar:**
- List of profile names, ⭐ marks default
- Click to select → right panel shows that profile's fields
- `[+ New]` button at bottom → opens inline name input → creates profile
- Right-click or `⋮` menu on profile → "Set as Default" / "Delete" (disabled for default)

**Right panel:**
- Profile name + default badge at top
- Same parameter fields as current (provider, endpoint, key, model, temperature, etc.)
- Auto-save on field change (debounced) or explicit Save button
- API key masked as `••••`, with 👁 toggle

**Collapsible routing section:**
- Two editable tables:
  - Agent → Profile mapping (`fixed_agent_routing`)
  - Action → Profile mapping (`action_routing`)
- Fallback chain as drag-reorderable tag list
- Only visible when expanded; collapsed by default

### Research/Chat Integration

When starting research or sending chat messages, the frontend currently sends a flat `llmConfig` object. After migration:
- The default profile's config is sent as the `llmConfig` (backward compat with backend's `session['llm_config']`)
- Additionally, the `defaultProfileName` is sent so the backend can use its routing system
- This is a minimal change: just change where the config values come from (from `settings.llm` to `settings.activeProfile`)

## Files to Modify

| File | Change |
|------|--------|
| `web/src/types/settings.ts` | Add `LLMProfile`, `LLMProfileRegistry`, `RoutingConfig` types; remove `BackendLLMConfig` |
| `web/src/store/useSettingsStore.ts` | Replace `llm`/`savedLlm` with `profiles`/`activeProfileName`; add profile CRUD actions; remove legacy API calls |
| `web/src/lib/api.ts` | Add 8 profile/routing API methods; remove `/llm/config` calls |
| `web/src/components/settings/LLMConfigPanel.tsx` | Complete rewrite: left sidebar + right form + routing section |
| `web/src/components/chat/ChatInput.tsx` | Read active profile instead of `settings.llm` for model display |

## Not In Scope

- Drag-and-drop profile reordering
- Profile import/export
- Profile usage statistics
- Per-session profile override in chat
- Visual companion/mockup tooling
