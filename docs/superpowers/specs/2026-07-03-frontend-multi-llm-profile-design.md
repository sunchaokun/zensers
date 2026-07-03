# Phase 3: Frontend Multi-LLM Profile UI Design

**Date:** 2026-07-03
**Status:** Draft (Revised — audit fixes applied)
**Revision notes:** Fixed 7 high/5 medium risks from audit. Key changes: (1) complete camelCase↔snake_case mapping tables, (2) API Key safe read-write protocol, (3) localStorage migration mapping code, (4) per-profile dirty tracking, (5) routing validation, (6) debounce & race condition handling, (7) empty-profile fallback.

## Goal

Migrate the frontend from a single flat LLM config form to a multi-profile management UI, fully wired to the backend `/api/v1/llm/profiles/*` and `/api/v1/llm/routing` endpoints.

## Design Decisions

1. **Layout**: Left sidebar profile list + right panel parameter form (VSCode Settings style)
2. **Routing config**: Collapsible section inside the profile panel, not a separate tab
3. **API migration**: Complete migration to `/profiles` endpoints; remove all `/llm/config` calls
4. **Backward compat**: The `POST /api/v1/llm/config` legacy endpoint remains on backend for any external callers, but frontend no longer uses it
5. **Naming convention**: Frontend internal types use **snake_case** matching the backend GET response (see §Field Mapping for the exact truth table); the `llm` compat getter translates to camelCase for downstream consumers
6. **API Key protocol**: GET returns masked `"***"` under key `apiKey`; PUT must **omit** `api_key` entirely when unchanged, send actual value only on explicit user input — never echo `"***"` back (see §API Key Safe Read-Write Protocol)
7. **Routing validation**: Frontend validates all profile names in routing config before PUT; only allows selecting from existing profile names via dropdown (see §Routing Validation)

---

## Field Mapping: The Single Source of Truth

The backend GET `/profiles` response uses a **mixed naming convention**: `asdict()` produces snake_case, then the endpoint manually **overwrites** `api_key` with `apiKey` and injects `hasApiKey`. This means the actual response has `apiKey` (camelCase) instead of `api_key`, plus an extra `hasApiKey` field.

### GET Response → Frontend `LLMProfile` Type

| Backend GET response key | Frontend `LLMProfile` field | Type | Notes |
|--------------------------|----------------------------|------|-------|
| `name` | `name` | `string` | |
| `display_name` | `display_name` | `string` | |
| `provider` | `provider` | `string` | |
| `apiKey` ⚠️ | `api_key` | `string` | Response uses `apiKey` (camelCase, masked); backend strips `api_key` from response. Frontend normalizes `apiKey → api_key` on parse |
| `base_url` | `base_url` | `string` | |
| `model` | `model` | `string` | |
| `fallback_model` | `fallback_model` | `string` | |
| `temperature` | `temperature` | `number` | |
| `max_tokens` | `max_tokens` | `number` | |
| `top_p` | `top_p` | `number` | |
| `frequency_penalty` | `frequency_penalty` | `number` | |
| `presence_penalty` | `presence_penalty` | `number` | |
| `max_context_tokens` | `max_context_tokens` | `number` | |
| `cost_limit_per_call` | `cost_limit_per_call` | `number` | Not enforced by backend; **not exposed in UI** (reserved field) |
| `is_default` | `is_default` | `boolean` | |
| `enabled` | `enabled` | `boolean` | |
| `created_at` | `created_at` | `string` | May be empty `""`; display only if non-empty |
| `updated_at` | `updated_at` | `string` | May be empty `""`; display only if non-empty |
| `hasApiKey` ⚠️ | `hasApiKey` | `boolean` | Computed by backend; frontend uses this to decide API key input placeholder |

**Parse normalization**: When `loadProfiles()` receives the GET response, it must:
1. Remap `apiKey → api_key` (masked value, `"***"` or `""`)
2. Keep `hasApiKey` as-is

```typescript
function normalizeProfileResponse(raw: Record<string, any>): LLMProfile {
  const { apiKey, hasApiKey, ...rest } = raw;
  return {
    ...rest,
    api_key: apiKey ?? '',
    hasApiKey: hasApiKey ?? false,
  } as LLMProfile;
}
```

### Frontend `LLMProfile` → PUT Request Body

| Frontend field | PUT request key | Type | Notes |
|---------------|-----------------|------|-------|
| `name` | `name` | `string` | Only in POST (create); not in PUT |
| `display_name` | `display_name` | `string` | |
| `provider` | `provider` | `string` | |
| `api_key` | `api_key` | `string` | **Special**: omit entirely if unchanged; send actual value only if user modified (see §API Key Protocol) |
| `base_url` | `base_url` | `string` | |
| `model` | `model` | `string` | |
| `fallback_model` | `fallback_model` | `string` | |
| `temperature` | `temperature` | `number` | |
| `max_tokens` | `max_tokens` | `number` | |
| `top_p` | `top_p` | `number` | |
| `frequency_penalty` | `frequency_penalty` | `number` | |
| `presence_penalty` | `presence_penalty` | `number` | |
| `max_context_tokens` | `max_context_tokens` | `number` | |
| `cost_limit_per_call` | `cost_limit_per_call` | `number` | |
| `enabled` | `enabled` | `boolean` | |

All PUT request keys are **snake_case** — matching the backend `LLMProfile` dataclass field names. The backend uses `hasattr(p, k)` + `setattr(p, k, v)` to apply updates, so only valid snake_case field names are accepted; camelCase keys are silently ignored.

### `llm` Compat Getter: `LLMProfile` → `LLMConfig` (camelCase)

This getter is the bridge that lets `useResearch.ts`, `ChatInput.tsx`, etc. continue reading `llm.model`, `llm.apiKey`, `llm.apiEndpoint` without changes.

| `LLMProfile` field (source) | `LLMConfig` field (target) | Transform |
|-----------------------------|---------------------------|-----------|
| `provider` | `provider` | Direct |
| `api_key` | `apiKey` | Rename |
| `base_url` | `apiEndpoint` | Rename ⚠️ |
| `model` | `model` | Direct |
| `temperature` | `temperature` | Direct |
| `max_tokens` | `maxTokens` | Rename |
| `top_p` | `topP` | Rename |
| `frequency_penalty` | `frequencyPenalty` | Rename |
| `presence_penalty` | `presencePenalty` | Rename |

**Fallback**: If `profiles[activeProfileName]` is `undefined` (loading, error, empty), return `DEFAULT_SETTINGS.llm` instead of crashing.

```typescript
const llm = computed(() => {
  const p = profiles.value[activeProfileName.value];
  if (!p) return { ...DEFAULT_SETTINGS.llm };
  return {
    provider: p.provider as LLMProvider,
    apiKey: p.api_key,
    apiEndpoint: p.base_url,
    model: p.model,
    temperature: p.temperature,
    maxTokens: p.max_tokens,
    topP: p.top_p,
    frequencyPenalty: p.frequency_penalty,
    presencePenalty: p.presence_penalty,
  };
});
```

---

## API Key Safe Read-Write Protocol

The backend masks API keys in GET responses (`"***"` if set, `""` if empty). The frontend must never accidentally overwrite a real key with the masked placeholder.

### Rules

1. **On load** (`loadProfiles()`): Store `api_key: "***"` as-is in the local `LLMProfile`. Store `hasApiKey: true/false` alongside it. The API key input displays `"••••••••"` as placeholder when `hasApiKey === true` and `api_key === "***"`; the input value is **empty string**.

2. **On render**: The API key `<Input>` shows:
   - Placeholder `"•••••••• (已设置)"` when `hasApiKey === true` and input is empty
   - Placeholder `"sk-..."` when `hasApiKey === false`
   - Actual value only when user types something

3. **On save** (`updateProfile()`): Build the PUT body by:
   - If user **did not touch** the API key input: **omit `api_key` from the PUT body entirely**
   - If user **cleared** the API key input: send `api_key: ""` (backend will clear it)
   - If user **entered a new value**: send `api_key: <new_value>`
   - **Never** send `api_key: "***"` — the backend filters this out, but relying on that is fragile

4. **Track dirty state**: A separate `apiKeyModified: boolean` per profile tracks whether the user touched the key input. Reset after successful save.

### Implementation sketch

```typescript
function buildUpdatePayload(profile: LLMProfile, modifiedFields: Set<string>, apiKeyInputValue: string): Record<string, any> {
  const payload: Record<string, any> = {};
  for (const field of modifiedFields) {
    if (field === 'api_key') {
      if (apiKeyInputValue === '' && profile.hasApiKey) {
        payload.api_key = '';
      } else if (apiKeyInputValue !== '' && apiKeyInputValue !== '***') {
        payload.api_key = apiKeyInputValue;
      }
    } else {
      payload[field] = (profile as any)[field];
    }
  }
  return payload;
}
```

---

## Architecture

### Data Flow

```
User edits profile in UI
  → useSettingsStore.updateProfile(name, modifiedFields)
    → api.updateLLMProfile(name, buildUpdatePayload(...))
      → PUT /api/v1/llm/profiles/{name}  (snake_case body, api_key omitted if unchanged)
    → store.profiles[name] updated locally (merge response or re-fetch)
    → if name === activeProfileName, llm compat getter auto-updates
    → saveToStorage() persists profiles to localStorage
```

### Type Changes (`settings.ts`)

New types mirroring backend dataclasses (snake_case, matching PUT request format):

```typescript
interface LLMProfile {
  name: string;
  display_name: string;
  provider: string;
  api_key: string;
  hasApiKey: boolean;
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

interface RoutingConfig {
  fixed_agent_routing: Record<string, string>;
  action_routing: Record<string, string>;
  fallback_chain: string[];
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
- `routingConfig: RoutingConfig`

Helper `activeProfile` getter derives the selected `LLMProfile` from `profiles[activeProfileName]`, with fallback to a default empty profile.

**Constants**: Add `DEFAULT_LLM_PROFILE: LLMProfile` with sensible defaults mirroring the backend dataclass defaults, used for new profile creation and empty-state fallback.

### Store Changes (`useSettingsStore.ts`)

New state:
- `profiles: Record<string, LLMProfile>` — replaces `llm`/`savedLlm`
- `savedProfiles: Record<string, LLMProfile>` — for per-profile dirty tracking (see §Dirty Tracking)
- `activeProfileName: string`
- `defaultProfileName: string`
- `routingConfig: RoutingConfig`
- `apiKeyModified: Record<string, boolean>` — tracks whether user touched API key per profile
- `isLoadingProfiles: boolean` — loading state for profile fetch

New actions:
- `loadProfiles()` → `GET /api/v1/llm/profiles` → normalize `apiKey → api_key` → populate `profiles`, `savedProfiles`, `defaultProfileName`, `routingConfig`; set `activeProfileName = defaultProfileName` if not already set
- `createProfile(data)` → `POST /api/v1/llm/profiles` → on success, add to `profiles` + `savedProfiles`
- `updateProfile(name, fields, apiKeyChanged?, apiKeyValue?)` → build payload using §API Key Protocol → `PUT /api/v1/llm/profiles/{name}` → on success, update `profiles[name]` + `savedProfiles[name]`
- `deleteProfile(name)` → `DELETE /api/v1/llm/profiles/{name}` → on success, remove from `profiles` + `savedProfiles`; if deleted was active, switch to default; refresh profiles from backend to get updated `is_default`
- `setDefaultProfile(name)` → `POST /api/v1/llm/profiles/{name}/default` → on success, update `defaultProfileName`; refresh all profiles to get updated `is_default` flags
- `switchProfile(name)` → sets `activeProfileName`; no API call
- `updateRouting(config)` → validate (see §Routing Validation) → `PUT /api/v1/llm/routing` → on success, update `routingConfig`

Removed:
- `persistLLMConfig()` — replaced by `updateProfile()` (auto-persists on every change)
- `syncConfigToBackend()` — replaced by `loadProfiles()` on mount
- `applyBackendConfig()` — replaced by `loadProfiles()` on mount
- `savedLlm` state — replaced by `savedProfiles` (per-profile dirty tracking)

Compatibility:
- `llm` getter remains as a computed property that returns `profiles[activeProfileName]` mapped to the old `LLMConfig` shape (see §llm Compat Getter table). Fallback to `DEFAULT_SETTINGS.llm` if profile not found.
- `updateLLMConfig()` becomes a compat wrapper that calls `updateProfile(activeProfileName, mapCamelToSnake(fields))`
- `switchProvider()` becomes a compat wrapper that updates the active profile's provider + defaults from `PROVIDER_DEFAULTS`. **Behavior change**: no longer clears `api_key` when switching provider (user may switch back and forth while debugging; clearing is unexpected). Provider defaults now map to `base_url` (not `apiEndpoint`) and `max_tokens` (not `maxTokens`).

### Dirty Tracking

Per-profile dirty detection replaces the old single `savedLlm` approach:

```typescript
function isProfileDirty(name: string): boolean {
  const current = profiles[name];
  const saved = savedProfiles[name];
  if (!current || !saved) return false;
  const { hasApiKey: _h, ...currentClean } = current;
  const { hasApiKey: _h2, ...savedClean } = saved;
  return JSON.stringify(currentClean) !== JSON.stringify(savedClean);
}
```

- `savedProfiles` is set from the backend response on `loadProfiles()` and after each successful `updateProfile()`
- `hasApiKey` is excluded from comparison (it's a computed field that may differ between local and backend state)
- The `apiKeyModified` map tracks whether the user explicitly touched the API key input for a profile

### API Client Changes (`api.ts`)

New methods:
- `getLLMProfiles()` → `GET /api/v1/llm/profiles` → returns raw response
- `getLLMProfile(name)` → `GET /api/v1/llm/profiles/{name}` → returns raw response
- `createLLMProfile(data)` → `POST /api/v1/llm/profiles` → body is snake_case
- `updateLLMProfile(name, data)` → `PUT /api/v1/llm/profiles/{name}` → body is snake_case; `api_key` omitted if unchanged
- `deleteLLMProfile(name)` → `DELETE /api/v1/llm/profiles/{name}`
- `setDefaultLLMProfile(name)` → `POST /api/v1/llm/profiles/{name}/default`
- `getLLMRouting()` → `GET /api/v1/llm/routing`
- `updateLLMRouting(data)` → `PUT /api/v1/llm/routing`

**Response normalization**: `getLLMProfiles()` and `getLLMProfile()` must normalize the response before returning — remap `apiKey → api_key`:
```typescript
function normalizeProfileResponse(raw: Record<string, any>): LLMProfile {
  const { apiKey, hasApiKey, ...rest } = raw;
  return {
    ...rest,
    api_key: apiKey ?? '',
    hasApiKey: hasApiKey ?? false,
  } as LLMProfile;
}
```

Removed:
- All calls to `POST /api/v1/llm/config` and `GET /api/v1/llm/config`
- The `POST /api/v1/llm/config` method is kept in `api.ts` (may be used elsewhere) but removed from the store

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
- List of profile names, ⭐ marks default. Display text: `profile.display_name || profile.name`
- Click to select → right panel shows that profile's fields
- `[+ New]` button at bottom → opens inline name input → validates name (alphanumeric + hyphens, no spaces, non-empty, not duplicate) → creates profile via `POST /api/v1/llm/profiles`
- `⋮` menu on profile → "Set as Default" / "Delete" (disabled for default profile)
- Delete confirmation dialog: confirm before calling `DELETE`; on 400 error (e.g. someone else changed default), refresh profiles and show toast

**Right panel:**
- Profile name + default badge at top
- Same parameter fields as current (provider, endpoint, key, model, temperature, etc.)
- Fields are snake_case internally but displayed with Chinese labels
- **Auto-save**: debounced 500ms after field change. Switching profile cancels the pending debounce timer. On debounce fire, call `updateProfile()` with only the modified fields (tracked via a `modifiedFields: Set<string>` per profile edit session).
- **Explicit Save button**: also available; saves immediately (cancels pending debounce first)
- API key input: follows §API Key Safe Read-Write Protocol — placeholder shows "•••••••• (已设置)" when `hasApiKey && !apiKeyModified`, value is empty by default
- Save status indicator: "已保存" / "保存中..." / "保存失败: <error>" (auto-dismiss after 5s)
- `max_context_tokens` exposed as an advanced field (collapsed by default)
- `cost_limit_per_call` **not exposed** (backend does not enforce it; adding it would mislead users)

**Collapsible routing section:**
- Two editable tables:
  - Agent → Profile mapping (`fixed_agent_routing`) — profile column is a **dropdown** of existing profile names, not free text
  - Action → Profile mapping (`action_routing`) — profile column is a **dropdown** of existing profile names
- Fallback chain as tag list with up/down reorder buttons (not drag-and-drop — out of scope)
- Only visible when expanded; collapsed by default
- **Validation before save**: all profile name values must exist in `profiles` keys (see §Routing Validation)

**Reset button**: Calls `DELETE /api/v1/llm/profiles/{name}` for each non-default profile, then resets the default profile to backend defaults via `POST /api/v1/llm/config/reset` → `loadProfiles()`. Confirmation dialog required.

### Routing Validation

Before calling `PUT /api/v1/llm/routing`, the frontend validates:

```typescript
function validateRoutingConfig(config: RoutingConfig, profileNames: string[]): string[] {
  const errors: string[] = [];
  for (const [agent, profileName] of Object.entries(config.fixed_agent_routing)) {
    if (!profileNames.includes(profileName)) {
      errors.push(`Agent "${agent}" 引用了不存在的 profile "${profileName}"`);
    }
  }
  for (const [action, profileName] of Object.entries(config.action_routing)) {
    if (!profileNames.includes(profileName)) {
      errors.push(`Action "${action}" 引用了不存在的 profile "${profileName}"`);
    }
  }
  for (const name of config.fallback_chain) {
    if (!profileNames.includes(name)) {
      errors.push(`Fallback chain 引用了不存在的 profile "${name}"`);
    }
  }
  return errors;
}
```

If errors are non-empty, show validation messages and block save. Additionally, the routing table dropdowns only allow selecting from existing profile names, preventing typos at the input level.

### Debounce & Race Condition Handling

```typescript
const pendingSaveRef = useRef<Map<string, NodeJS.Timeout>>(new Map());

function scheduleSave(profileName: string, fields: Record<string, any>) {
  const existing = pendingSaveRef.current.get(profileName);
  if (existing) clearTimeout(existing);
  const timer = setTimeout(async () => {
    pendingSaveRef.current.delete(profileName);
    await updateProfile(profileName, fields);
  }, 500);
  pendingSaveRef.current.set(profileName, timer);
}

function cancelPendingSave(profileName: string) {
  const existing = pendingSaveRef.current.get(profileName);
  if (existing) {
    clearTimeout(existing);
    pendingSaveRef.current.delete(profileName);
  }
}
```

- When user switches profile, call `cancelPendingSave(oldProfileName)` — unsaved changes are kept in `profiles` locally but not persisted. A dirty indicator shows on the sidebar item.
- When user navigates away from the settings page, warn if any profile has unsaved changes (iterate `profiles` vs `savedProfiles`).
- On network failure: show error toast, keep local changes, do not revert. User can retry.

### Research/Chat Integration

When starting research or sending chat messages, the frontend currently sends a flat `llmConfig` object (in `useResearch.ts` lines 52-62 and 148-158). After migration:
- The `llm` compat getter ensures `useResearch.ts` continues to work without changes — it reads `llm.model`, `llm.apiKey` etc., which are derived from `profiles[activeProfileName]` via the mapping table in §llm Compat Getter
- **No changes needed** in `useResearch.ts` or `ChatInput.tsx` — the compat getter provides identical shape
- Optionally, future work can send `profileName` alongside `llmConfig` so the backend can use its routing system instead of the flat config override

---

## Files to Modify

| File | Change |
|------|--------|
| `web/src/types/settings.ts` | Add `LLMProfile`, `LLMProfileRegistry`, `RoutingConfig` types (with `hasApiKey`); add `DEFAULT_LLM_PROFILE` constant; keep `LLMConfig` as compat alias |
| `web/src/store/useSettingsStore.ts` | Add `profiles`/`savedProfiles`/`activeProfileName`/`defaultProfileName`/`routingConfig`/`apiKeyModified`/`isLoadingProfiles` state; add profile CRUD actions; add `normalizeProfileResponse()`; keep `llm` as computed getter for compat; keep `updateLLMConfig`/`switchProvider` as compat wrappers; implement per-profile dirty tracking; add debounce/cancel logic |
| `web/src/lib/api.ts` | Add 8 profile/routing API methods with response normalization; keep `POST /llm/config` method (may be used elsewhere) |
| `web/src/components/settings/LLMConfigPanel.tsx` | Complete rewrite: left sidebar + right form + routing section; implement API Key safe protocol; implement debounce; implement routing validation |
| `web/src/hooks/useResearch.ts` | **No changes needed** — `llm` compat getter provides identical interface |
| `web/src/components/chat/ChatInput.tsx` | **No changes needed** — `llm` compat getter provides identical interface |

### Compat Strategy

The `llm` getter in the store returns `profiles[activeProfileName]` mapped to the old `LLMConfig` shape (camelCase) per the mapping table in §llm Compat Getter. This ensures:
- `useResearch.ts` can keep reading `llm.model`, `llm.apiKey`, `llm.apiEndpoint` etc. — no change needed
- `ChatInput.tsx` can keep reading `llm.model`, `llm.provider` — no change needed
- Only `LLMConfigPanel.tsx` needs a full rewrite; other components are unaffected

---

## localStorage Persistence

The store currently persists `llm` to `localStorage` under `Zensers-settings-v2`. After migration:
- `profiles`, `savedProfiles`, `activeProfileName`, `defaultProfileName`, `routingConfig` are persisted to localStorage
- On load: localStorage profiles are used as cache, then `loadProfiles()` fetches from backend and overwrites if backend has data
- The `llm` compat getter reads from `profiles[activeProfileName]`, so localStorage format changes but downstream consumers are unaffected

### Migration: Old `llm` Format → New `profiles` Format

If localStorage has old `llm` but no `profiles`, convert the old `llm` into a single "migrated" profile. This mirrors the backend's own `_migrate_legacy_to_profile()` logic (`settings.py:642-659`).

**Complete mapping table:**

| Old localStorage `llm` field | New `LLMProfile` field | Transform | Default if missing |
|------------------------------|----------------------|-----------|-------------------|
| `provider` | `provider` | Direct | `"openai"` |
| `apiKey` | `api_key` | Rename ⚠️ | `""` |
| — | `hasApiKey` | `!!apiKey` | `false` |
| `apiEndpoint` | `base_url` | Rename ⚠️ | `"https://api.openai.com/v1"` |
| `model` | `model` | Direct | `"gpt-4o"` |
| — | `fallback_model` | N/A | `""` |
| `temperature` | `temperature` | Direct | `0.7` |
| `maxTokens` | `max_tokens` | Rename ⚠️ | `4096` |
| `topP` | `top_p` | Rename ⚠️ | `1.0` |
| `frequencyPenalty` | `frequency_penalty` | Rename ⚠️ | `0.0` |
| `presencePenalty` | `presence_penalty` | Rename ⚠️ | `0.0` |
| — | `max_context_tokens` | N/A | `128000` |
| — | `cost_limit_per_call` | N/A | `0.0` |
| — | `name` | Hardcoded | `"migrated"` |
| — | `display_name` | Hardcoded | `"迁移配置"` |
| — | `is_default` | Hardcoded | `true` |
| — | `enabled` | Hardcoded | `true` |
| — | `created_at` | Hardcoded | `""` |
| — | `updated_at` | Hardcoded | `""` |

**Implementation:**

```typescript
function migrateLlmToProfile(llm: LLMConfig): LLMProfile {
  return {
    name: 'migrated',
    display_name: '迁移配置',
    provider: llm.provider,
    api_key: llm.apiKey,
    hasApiKey: !!llm.apiKey,
    base_url: llm.apiEndpoint,
    model: llm.model,
    fallback_model: '',
    temperature: llm.temperature,
    max_tokens: llm.maxTokens,
    top_p: llm.topP,
    frequency_penalty: llm.frequencyPenalty,
    presence_penalty: llm.presencePenalty,
    max_context_tokens: 128000,
    cost_limit_per_call: 0.0,
    is_default: true,
    enabled: true,
    created_at: '',
    updated_at: '',
  };
}
```

**Init flow:**

```typescript
function getInitialState() {
  const persisted = loadFromStorage();
  if (persisted?.profiles && Object.keys(persisted.profiles).length > 0) {
    // New format — use directly
    return { ...INITIAL_DATA, ...persisted };
  }
  if (persisted?.llm) {
    // Old format — migrate
    const profile = migrateLlmToProfile(persisted.llm);
    return {
      ...INITIAL_DATA,
      profiles: { migrated: profile },
      savedProfiles: { migrated: profile },
      activeProfileName: 'migrated',
      defaultProfileName: 'migrated',
    };
  }
  // No data — use defaults
  return { ...INITIAL_DATA };
}
```

---

## Backend Gaps (file follow-up issues)

These are backend problems discovered during the audit that are **not in scope** for this frontend PR but should be tracked:

1. **`cost_limit_per_call` not enforced**: `LLMProfile.cost_limit_per_call` exists but `call_llm()` only checks `LLMConfig.cost_limit_per_report`. Frontend does not expose this field until backend enforces it.
2. **`PUT /routing` no validation**: Backend accepts any profile name strings without checking existence. Frontend validates client-side, but backend should also validate.
3. **`created_at`/`updated_at` never auto-set**: Backend returns empty strings for these fields. Should be set on creation/update.
4. **GET response mixed naming** (FIXED): `asdict()` used to produce `api_key` (plaintext) alongside injected `apiKey` (masked). Now fixed: backend pops `api_key` from response dict before returning. Frontend still normalizes `apiKey → api_key` on parse for consistent internal naming.

---

## Not In Scope

- Drag-and-drop profile reordering (using up/down buttons instead)
- Profile import/export
- Profile usage statistics
- Per-session profile override in chat
- Visual companion/mockup tooling
- Backend fixes for the gaps listed above
