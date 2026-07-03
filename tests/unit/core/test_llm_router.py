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
        assert result.name == "fast"

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
        assert result.name == "strong"


class TestLLMRouterPriorityOrder:
    def test_explicit_override_takes_priority_over_agent_mapping(self):
        router = LLMRouter(_make_registry())
        hint = RoutingHint(agent_type="quality_check", profile_name="fast")
        result = router.resolve(hint)
        assert result.name == "fast"

    def test_agent_mapping_takes_priority_over_action_mapping(self):
        registry = _make_registry()
        registry.fixed_agent_routing["quality_check"] = "strong"
        registry.action_routing["quality_check"] = "fast"
        router = LLMRouter(registry)
        hint = RoutingHint(agent_type="quality_check", action="quality_check")
        result = router.resolve(hint)
        assert result.name == "strong"
