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
            cost_limit_per_call=0.5,
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
