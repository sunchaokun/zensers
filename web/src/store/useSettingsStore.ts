import { create } from 'zustand';
import type { LLMConfig, ThemeConfig, UploadedFile, LLMModel, AppSettings, LLMProfile, RoutingConfig } from '@/types/settings';
import { DEFAULT_SETTINGS, PROVIDER_DEFAULTS, PRESET_MODELS, DEFAULT_LLM_PROFILE, normalizeProfileResponse, profileToLLMConfig, migrateLlmToProfile } from '@/types/settings';

const STORAGE_KEY = 'Zensers-settings-v2';
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function loadFromStorage(): Record<string, any> | null {
  if (typeof localStorage === 'undefined') return null;
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      return JSON.parse(stored);
    }
  } catch {}
  return null;
}

function saveToStorage(state: SettingsState & SettingsMethods) {
  if (typeof localStorage === 'undefined') return;
  try {
    const data = JSON.stringify({
      state: {
        profiles: state.profiles,
        activeProfileName: state.activeProfileName,
        defaultProfileName: state.defaultProfileName,
        routingConfig: state.routingConfig,
        theme: state.theme,
        language: state.language,
        sendOnEnter: state.sendOnEnter,
        showTokenCount: state.showTokenCount,
        autoSaveDraft: state.autoSaveDraft,
      },
      version: 1,
    });
    localStorage.setItem(STORAGE_KEY, data);
  } catch (e) {
    console.error('[persist] FAILED to save settings:', e);
  }
}

type SettingsMethods = {
  updateLLMConfig: (config: Partial<LLMConfig>) => void;
  persistLLMConfig: () => Promise<void>;
  applyBackendConfig: (config: any) => void;
  syncConfigToBackend: () => Promise<void>;
  updateThemeConfig: (config: Partial<ThemeConfig>) => void;
  updateSettings: (settings: Partial<AppSettings>) => void;
  resetSettings: () => void;
  loadModels: () => Promise<void>;
  addUploadedFile: (file: UploadedFile) => void;
  updateUploadedFile: (id: string, updates: Partial<UploadedFile>) => void;
  removeUploadedFile: (id: string) => void;
  clearUploadedFiles: () => void;
  switchProvider: (provider: LLMConfig['provider']) => void;
  loadProfiles: () => Promise<void>;
  createProfile: (data: Record<string, any>) => Promise<void>;
  updateProfile: (name: string, fields: Record<string, any>) => Promise<void>;
  deleteProfile: (name: string) => Promise<void>;
  setDefaultProfile: (name: string) => Promise<void>;
  switchProfile: (name: string) => void;
  updateRouting: (config: RoutingConfig) => Promise<void>;
};

interface SettingsState {
  profiles: Record<string, LLMProfile>;
  savedProfiles: Record<string, LLMProfile>;
  activeProfileName: string;
  defaultProfileName: string;
  routingConfig: RoutingConfig;
  isLoadingProfiles: boolean;

  llm: LLMConfig;
  savedLlm: LLMConfig;
  isSaving: boolean;
  saveError: string | null;

  theme: ThemeConfig;
  language: string;
  sendOnEnter: boolean;
  showTokenCount: boolean;
  autoSaveDraft: boolean;

  uploadedFiles: UploadedFile[];
  availableModels: LLMModel[];
}

const INITIAL_PROFILES: Record<string, LLMProfile> = {};
const INITIAL_ROUTING: RoutingConfig = { fixed_agent_routing: {}, action_routing: {}, fallback_chain: [] };

function getInitialState(): Omit<SettingsState, keyof SettingsMethods> {
  if (typeof window === 'undefined') {
    return {
      profiles: INITIAL_PROFILES,
      savedProfiles: INITIAL_PROFILES,
      activeProfileName: '',
      defaultProfileName: '',
      routingConfig: INITIAL_ROUTING,
      isLoadingProfiles: false,
      llm: { ...DEFAULT_SETTINGS.llm },
      savedLlm: { ...DEFAULT_SETTINGS.llm },
      isSaving: false,
      saveError: null,
      theme: { ...DEFAULT_SETTINGS.theme },
      language: DEFAULT_SETTINGS.language,
      sendOnEnter: DEFAULT_SETTINGS.sendOnEnter,
      showTokenCount: DEFAULT_SETTINGS.showTokenCount,
      autoSaveDraft: DEFAULT_SETTINGS.autoSaveDraft,
      uploadedFiles: [],
      availableModels: PRESET_MODELS,
    };
  }

  const persisted = loadFromStorage();
  if (persisted?.state?.profiles && Object.keys(persisted.state.profiles).length > 0) {
    const st = persisted.state;
    const activeProfile = st.profiles[st.activeProfileName];
    const llm = activeProfile ? profileToLLMConfig(activeProfile) : { ...DEFAULT_SETTINGS.llm };
    return {
      profiles: st.profiles,
      savedProfiles: st.savedProfiles || st.profiles,
      activeProfileName: st.activeProfileName || '',
      defaultProfileName: st.defaultProfileName || '',
      routingConfig: st.routingConfig || INITIAL_ROUTING,
      isLoadingProfiles: false,
      llm,
      savedLlm: { ...llm },
      isSaving: false,
      saveError: null,
      theme: { ...DEFAULT_SETTINGS.theme, ...(st.theme || {}) },
      language: st.language ?? DEFAULT_SETTINGS.language,
      sendOnEnter: st.sendOnEnter ?? DEFAULT_SETTINGS.sendOnEnter,
      showTokenCount: st.showTokenCount ?? DEFAULT_SETTINGS.showTokenCount,
      autoSaveDraft: st.autoSaveDraft ?? DEFAULT_SETTINGS.autoSaveDraft,
      uploadedFiles: [],
      availableModels: PRESET_MODELS,
    };
  }

  if (persisted?.state?.llm) {
    const profile = migrateLlmToProfile(persisted.state.llm);
    return {
      profiles: { migrated: profile },
      savedProfiles: { migrated: profile },
      activeProfileName: 'migrated',
      defaultProfileName: 'migrated',
      routingConfig: INITIAL_ROUTING,
      isLoadingProfiles: false,
      llm: { ...DEFAULT_SETTINGS.llm, ...persisted.state.llm },
      savedLlm: { ...DEFAULT_SETTINGS.llm, ...persisted.state.llm },
      isSaving: false,
      saveError: null,
      theme: { ...DEFAULT_SETTINGS.theme, ...(persisted.state.theme || {}) },
      language: persisted.state.language ?? DEFAULT_SETTINGS.language,
      sendOnEnter: persisted.state.sendOnEnter ?? DEFAULT_SETTINGS.sendOnEnter,
      showTokenCount: persisted.state.showTokenCount ?? DEFAULT_SETTINGS.showTokenCount,
      autoSaveDraft: persisted.state.autoSaveDraft ?? DEFAULT_SETTINGS.autoSaveDraft,
      uploadedFiles: [],
      availableModels: PRESET_MODELS,
    };
  }

  return {
    profiles: INITIAL_PROFILES,
    savedProfiles: INITIAL_PROFILES,
    activeProfileName: '',
    defaultProfileName: '',
    routingConfig: INITIAL_ROUTING,
    isLoadingProfiles: false,
    llm: { ...DEFAULT_SETTINGS.llm },
    savedLlm: { ...DEFAULT_SETTINGS.llm },
    isSaving: false,
    saveError: null,
    theme: { ...DEFAULT_SETTINGS.theme },
    language: DEFAULT_SETTINGS.language,
    sendOnEnter: DEFAULT_SETTINGS.sendOnEnter,
    showTokenCount: DEFAULT_SETTINGS.showTokenCount,
    autoSaveDraft: DEFAULT_SETTINGS.autoSaveDraft,
    uploadedFiles: [],
    availableModels: PRESET_MODELS,
  };
}

function _syncLLMFromProfiles(profiles: Record<string, LLMProfile>, activeName: string): LLMConfig {
  const p = profiles[activeName];
  return p ? profileToLLMConfig(p) : { ...DEFAULT_SETTINGS.llm };
}

const _initial = getInitialState();

export const useSettingsStore = create<SettingsState & SettingsMethods>()((set, get) => ({
  ..._initial,

  loadProfiles: async () => {
    set({ isLoadingProfiles: true });
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 15000);
      const res = await fetch(`${API_BASE_URL}/api/v1/llm/profiles`, { signal: controller.signal });
      clearTimeout(timeoutId);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      const profiles: Record<string, LLMProfile> = {};
      for (const [name, raw] of Object.entries(data.profiles || {})) {
        profiles[name] = normalizeProfileResponse(raw as Record<string, any>);
      }

      const defaultProfileName = data.default_profile || '';
      const currentActive = get().activeProfileName;
      const activeProfileName = (currentActive && profiles[currentActive]) ? currentActive : defaultProfileName;
      const routingConfig: RoutingConfig = {
        fixed_agent_routing: data.fixed_agent_routing || {},
        action_routing: data.action_routing || {},
        fallback_chain: data.fallback_chain || [],
      };

      const llm = _syncLLMFromProfiles(profiles, activeProfileName);
      set({
        profiles,
        savedProfiles: JSON.parse(JSON.stringify(profiles)),
        defaultProfileName,
        activeProfileName,
        routingConfig,
        llm,
        savedLlm: { ...llm },
        isLoadingProfiles: false,
      });
      saveToStorage(get());
    } catch (e) {
      console.error('[loadProfiles] failed:', e);
      set({ isLoadingProfiles: false });
    }
  },

  createProfile: async (data) => {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 10000);
      const res = await fetch(`${API_BASE_URL}/api/v1/llm/profiles`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
        signal: controller.signal,
      });
      clearTimeout(timeoutId);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const name = data.name;
      const profile: LLMProfile = { ...DEFAULT_LLM_PROFILE, ...data, hasApiKey: !!data.api_key };
      set((state) => {
        const profiles = { ...state.profiles, [name]: profile };
        const llm = _syncLLMFromProfiles(profiles, state.activeProfileName);
        return { profiles, savedProfiles: { ...state.savedProfiles, [name]: { ...profile } }, llm, savedLlm: { ...llm } };
      });
      saveToStorage(get());
    } catch (e: any) {
      throw e;
    }
  },

  updateProfile: async (name, fields) => {
    set({ isSaving: true, saveError: null });
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 15000);
      const res = await fetch(`${API_BASE_URL}/api/v1/llm/profiles/${name}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fields),
        signal: controller.signal,
      });
      clearTimeout(timeoutId);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      set((state) => {
        const existing = state.profiles[name] || DEFAULT_LLM_PROFILE;
        const updated = { ...existing, ...fields };
        if (fields.api_key !== undefined && fields.api_key !== '***') {
          updated.hasApiKey = !!fields.api_key;
        }
        const profiles = { ...state.profiles, [name]: updated };
        const llm = _syncLLMFromProfiles(profiles, state.activeProfileName);
        return {
          profiles,
          savedProfiles: { ...state.savedProfiles, [name]: { ...updated } },
          llm,
          savedLlm: { ...llm },
          isSaving: false,
          saveError: null,
        };
      });
      saveToStorage(get());
    } catch (e: any) {
      const msg = e?.name === 'AbortError' ? 'Request timed out' : String(e?.message || e);
      set({ isSaving: false, saveError: msg });
      setTimeout(() => {
        if (get().saveError === msg) set({ saveError: null });
      }, 5000);
      throw e;
    }
  },

  deleteProfile: async (name) => {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10000);
    const res = await fetch(`${API_BASE_URL}/api/v1/llm/profiles/${name}`, {
      method: 'DELETE',
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    set((state) => {
      const profiles = { ...state.profiles };
      delete profiles[name];
      const savedProfiles = { ...state.savedProfiles };
      delete savedProfiles[name];
      let activeProfileName = state.activeProfileName;
      if (activeProfileName === name) activeProfileName = state.defaultProfileName;
      const llm = _syncLLMFromProfiles(profiles, activeProfileName);
      return { profiles, savedProfiles, activeProfileName, llm, savedLlm: { ...llm } };
    });
    saveToStorage(get());
  },

  setDefaultProfile: async (name) => {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10000);
    const res = await fetch(`${API_BASE_URL}/api/v1/llm/profiles/${name}/default`, {
      method: 'POST',
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    set((state) => {
      const profiles = { ...state.profiles };
      for (const [k, p] of Object.entries(profiles)) {
        profiles[k] = { ...p, is_default: k === name };
      }
      return { defaultProfileName: name, profiles, savedProfiles: { ...profiles } };
    });
    saveToStorage(get());
  },

  switchProfile: (name) => {
    set((state) => {
      const llm = _syncLLMFromProfiles(state.profiles, name);
      return { activeProfileName: name, llm, savedLlm: { ...llm } };
    });
    saveToStorage(get());
  },

  updateRouting: async (config) => {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10000);
    const res = await fetch(`${API_BASE_URL}/api/v1/llm/routing`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    set({ routingConfig: config });
    saveToStorage(get());
  },

  // ========== Compat wrappers (keep downstream consumers working) ==========

  updateLLMConfig: (config) => {
    set((state) => {
      const newLlm = { ...state.llm, ...config };
      const activeName = state.activeProfileName;
      if (activeName && state.profiles[activeName]) {
        const p = state.profiles[activeName];
        const updated: LLMProfile = {
          ...p,
          provider: newLlm.provider,
          api_key: newLlm.apiKey,
          hasApiKey: !!newLlm.apiKey,
          base_url: newLlm.apiEndpoint,
          model: newLlm.model,
          temperature: newLlm.temperature,
          max_tokens: newLlm.maxTokens,
          top_p: newLlm.topP,
          frequency_penalty: newLlm.frequencyPenalty,
          presence_penalty: newLlm.presencePenalty,
        };
        const profiles = { ...state.profiles, [activeName]: updated };
        return { llm: newLlm, profiles };
      }
      return { llm: newLlm };
    });
  },

  persistLLMConfig: async () => {
    const current = get().llm;
    const activeName = get().activeProfileName;
    if (activeName) {
      const fields: Record<string, any> = {
        provider: current.provider,
        api_key: current.apiKey,
        base_url: current.apiEndpoint,
        model: current.model,
        temperature: current.temperature,
        max_tokens: current.maxTokens,
        top_p: current.topP,
        frequency_penalty: current.frequencyPenalty,
        presence_penalty: current.presencePenalty,
      };
      try {
        await get().updateProfile(activeName, fields);
      } catch (e) {
        // updateProfile already handles error state
      }
      return;
    }
    set({ isSaving: true, saveError: null });
    saveToStorage(get());
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 30000);
      const res = await fetch(`${API_BASE_URL}/api/v1/llm/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: current.provider,
          model: current.model,
          api_key: current.apiKey,
          api_endpoint: current.apiEndpoint,
          temperature: current.temperature,
          max_tokens: current.maxTokens,
          top_p: current.topP,
          frequency_penalty: current.frequencyPenalty,
          presence_penalty: current.presencePenalty,
        }),
        signal: controller.signal,
      });
      clearTimeout(timeoutId);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      set({ savedLlm: { ...current }, isSaving: false, saveError: null });
    } catch (e: any) {
      const msg = e?.name === 'AbortError' ? 'Request timed out' : String(e);
      set({ isSaving: false, saveError: msg });
      setTimeout(() => {
        if (get().saveError === msg) set({ saveError: null });
      }, 5000);
    }
  },

  applyBackendConfig: (config) => {
    const mapped: LLMConfig = {
      provider: config.provider as LLMConfig['provider'],
      model: config.model,
      apiKey: config.apiKey,
      apiEndpoint: config.apiEndpoint,
      temperature: config.temperature,
      maxTokens: config.maxTokens,
      topP: config.topP,
      frequencyPenalty: config.frequencyPenalty,
      presencePenalty: config.presencePenalty,
    };
    set({ llm: mapped, savedLlm: { ...mapped } });
  },

  syncConfigToBackend: async () => {
    await get().loadProfiles();
  },

  updateThemeConfig: (config) => {
    set((state) => ({ theme: { ...state.theme, ...config } }));
    saveToStorage(get());
  },

  updateSettings: (settings) => {
    set(settings);
    saveToStorage(get());
  },

  resetSettings: () => {
    const newLlm = { ...DEFAULT_SETTINGS.llm };
    set({
      llm: newLlm,
      savedLlm: { ...newLlm },
      theme: { ...DEFAULT_SETTINGS.theme },
      language: DEFAULT_SETTINGS.language,
      sendOnEnter: DEFAULT_SETTINGS.sendOnEnter,
      showTokenCount: DEFAULT_SETTINGS.showTokenCount,
      autoSaveDraft: DEFAULT_SETTINGS.autoSaveDraft,
      uploadedFiles: [],
    });
    saveToStorage(get());
  },

  addUploadedFile: (file) =>
    set((state) => ({
      uploadedFiles: [...state.uploadedFiles, file],
    })),

  updateUploadedFile: (id, updates) =>
    set((state) => ({
      uploadedFiles: state.uploadedFiles.map((f) =>
        f.id === id ? { ...f, ...updates } : f
      ),
    })),

  removeUploadedFile: (id) =>
    set((state) => ({
      uploadedFiles: state.uploadedFiles.filter((f) => f.id !== id),
    })),

  clearUploadedFiles: () =>
    set({ uploadedFiles: [] }),

  loadModels: async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/llm/models`);
      if (res.ok) {
        const data = await res.json();
        if (data.models?.length) {
          const mapped: LLMModel[] = data.models.map((m: any) => ({
            id: m.id,
            name: m.name,
            provider: m.provider,
            maxTokens: m.max_tokens ?? 128000,
          }));
          set({ availableModels: mapped });
        }
      }
    } catch {}
  },

  switchProvider: (provider) => {
    const defaults = PROVIDER_DEFAULTS[provider];
    set((state) => ({
      llm: {
        ...state.llm,
        provider,
        ...defaults,
        apiKey: provider === state.llm.provider ? state.llm.apiKey : '',
      },
    }));
  },
}));
