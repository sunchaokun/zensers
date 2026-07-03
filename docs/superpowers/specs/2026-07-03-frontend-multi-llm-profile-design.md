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

The existing `LLMConfig` type is kept as a compat alias. `BackendLLMConfig` is kept but deprecated (still used by the old `GET /api/v1/llm/config` response format, which we no longer call but may need for fallback). `AppSettings` extends to:
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
- `persistLLMConfig()` — replaced by `updateProfile()` (auto-persists on every change)
- `syncConfigToBackend()` — replaced by `loadProfiles()` on mount
- `applyBackendConfig()` — replaced by `loadProfiles()` on mount
- `savedLlm` state — dirty tracking moves to per-profile comparison

Compatibility:
- `llm` getter remains as a computed property that returns `profiles[activeProfileName]` mapped to the old `LLMConfig` shape. This ensures other components that read `settings.llm.model` etc. continue to work without changes.
- `updateLLMConfig()` becomes a compat wrapper that calls `updateProfile(activeProfileName, ...)`
- `switchProvider()` becomes a compat wrapper that updates the active profile's provider + defaults
- `savedLlm` is removed — dirty tracking moves to per-profile comparison

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

When starting research or sending chat messages, the frontend currently sends a flat `llmConfig` object (in `useResearch.ts` lines 52-62 and 148-158). After migration:
- The `llm` compat getter ensures `useResearch.ts` continues to work without changes — it reads `llm.model`, `llm.apiKey` etc., which are derived from `profiles[activeProfileName]`
- Optionally, future work can send `profileName` alongside `llmConfig` so the backend can use its routing system instead of the flat config override

## Files to Modify

| File | Change |
|------|--------|
| `web/src/types/settings.ts` | Add `LLMProfile`, `LLMProfileRegistry`, `RoutingConfig` types; keep `LLMConfig` as compat alias |
| `web/src/store/useSettingsStore.ts` | Add `profiles`/`activeProfileName`/`defaultProfileName`/`routingConfig` state; add profile CRUD actions; keep `llm` as computed getter for compat; keep `updateLLMConfig`/`switchProvider` as compat wrappers |
| `web/src/lib/api.ts` | Add 8 profile/routing API methods; keep `POST /llm/config` removal only from store, not from api.ts (it may be used elsewhere) |
| `web/src/components/settings/LLMConfigPanel.tsx` | Complete rewrite: left sidebar + right form + routing section |
| `web/src/hooks/useResearch.ts` | Change `llmConfig` construction to read from `activeProfile` instead of `llm` |
| `web/src/components/chat/ChatInput.tsx` | Read active profile model instead of `llm.model` for display |

### Compat Strategy

The `llm` getter in the store returns `profiles[activeProfileName]` mapped to the old `LLMConfig` shape (camelCase). This ensures:
- `useResearch.ts` can keep reading `llm.model`, `llm.apiKey` etc. — no change needed if we keep the getter
- `ChatInput.tsx` can keep reading `llm.model` — no change needed if we keep the getter
- Only `LLMConfigPanel.tsx` needs a full rewrite; other components are unaffected

## Not In Scope

- Drag-and-drop profile reordering
- Profile import/export
- Profile usage statistics
- Per-session profile override in chat
- Visual companion/mockup tooling

### localStorage Persistence

The store currently persists `llm` to `localStorage` under `Zensers-settings-v2`. After migration:
- `profiles`, `activeProfileName`, `defaultProfileName`, `routingConfig` are persisted to localStorage
- On load: localStorage profiles are used as cache, then `loadProfiles()` fetches from backend and overwrites if backend has data
- Migration path: if localStorage has old `llm` but no `profiles`, convert the old `llm` into a single "migrated" profile
- The `llm` compat getter reads from `profiles[activeProfileName]`, so localStorage format changes but downstream consumers are unaffected
