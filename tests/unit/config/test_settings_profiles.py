import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.config.llm_profiles import LLMProfile, LLMProfileRegistry
from src.config.settings import Settings, LLMConfig


@pytest.fixture(autouse=True)
def reset_settings(tmp_path):
    Settings._reset_instance()
    s = Settings()
    s._llm_profiles_persist_path = str(tmp_path / "llm_profiles.json")
    s.llm_profiles = LLMProfileRegistry(default_profile="migrated")
    s._migrate_legacy_to_profile()
    yield
    Settings._reset_instance()


def _profile(name="test", model="gpt-4o", api_key="sk-test"):
    return LLMProfile(name=name, model=model, api_key=api_key)


class TestSettingsProfileRegistry:
    def test_settings_has_llm_profiles_registry(self):
        s = Settings()
        assert hasattr(s, "llm_profiles")
        assert isinstance(s.llm_profiles, LLMProfileRegistry)

    def test_default_registry_has_migrated_profile(self):
        s = Settings()
        assert "migrated" in s.llm_profiles.profiles
        migrated = s.llm_profiles.profiles["migrated"]
        assert migrated.model == s.llm.model
        assert migrated.api_key == s.llm.api_key
        assert migrated.base_url == s.llm.base_url

    def test_default_profile_is_migrated(self):
        s = Settings()
        assert s.llm_profiles.default_profile == "migrated"


class TestSettingsProfileCRUD:
    def test_add_profile(self):
        s = Settings()
        p = _profile("strong", "gpt-4o", "sk-strong")
        s.add_llm_profile(p)
        assert "strong" in s.llm_profiles.profiles
        assert s.llm_profiles.profiles["strong"].model == "gpt-4o"

    def test_add_duplicate_name_raises(self):
        s = Settings()
        s.add_llm_profile(_profile("strong"))
        with pytest.raises(ValueError, match="already exists"):
            s.add_llm_profile(_profile("strong"))

    def test_update_profile(self):
        s = Settings()
        s.add_llm_profile(_profile("strong", "gpt-4o"))
        s.update_llm_profile("strong", model="gpt-4o-mini")
        assert s.llm_profiles.profiles["strong"].model == "gpt-4o-mini"

    def test_update_nonexistent_raises(self):
        s = Settings()
        with pytest.raises(KeyError, match="not found"):
            s.update_llm_profile("ghost", model="x")

    def test_delete_profile(self):
        s = Settings()
        s.add_llm_profile(_profile("fast"))
        s.delete_llm_profile("fast")
        assert "fast" not in s.llm_profiles.profiles

    def test_delete_default_profile_raises(self):
        s = Settings()
        with pytest.raises(ValueError, match="Cannot delete default"):
            s.delete_llm_profile("migrated")

    def test_set_default_profile(self):
        s = Settings()
        s.add_llm_profile(_profile("fast"))
        s.set_default_llm_profile("fast")
        assert s.llm_profiles.default_profile == "fast"

    def test_set_default_nonexistent_raises(self):
        s = Settings()
        with pytest.raises(KeyError, match="not found"):
            s.set_default_llm_profile("ghost")

    def test_list_profiles(self):
        s = Settings()
        s.add_llm_profile(_profile("strong"))
        s.add_llm_profile(_profile("fast"))
        names = s.list_llm_profiles()
        assert "migrated" in names
        assert "strong" in names
        assert "fast" in names


class TestSettingsSyncLlmFromProfiles:
    def test_sync_updates_llm_config_from_default_profile(self):
        s = Settings()
        s.add_llm_profile(_profile("custom", "claude-3", "sk-claude"))
        s.set_default_llm_profile("custom")
        s._sync_llm_config_from_profiles()
        assert s.llm.model == "claude-3"
        assert s.llm.api_key == "sk-claude"

    def test_sync_copies_all_fields(self):
        s = Settings()
        p = LLMProfile(name="full", model="gpt-4o", api_key="sk-f", base_url="https://f.api/v1",
                       temperature=0.5, max_tokens=8192, top_p=0.9,
                       frequency_penalty=0.1, presence_penalty=0.2)
        s.add_llm_profile(p)
        s.set_default_llm_profile("full")
        s._sync_llm_config_from_profiles()
        assert s.llm.model == "gpt-4o"
        assert s.llm.api_key == "sk-f"
        assert s.llm.base_url == "https://f.api/v1"
        assert s.llm.temperature == 0.5
        assert s.llm.max_tokens == 8192
        assert s.llm.top_p == 0.9
        assert s.llm.frequency_penalty == 0.1
        assert s.llm.presence_penalty == 0.2
