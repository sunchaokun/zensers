import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from src.config.llm_profiles import LLMProfile, LLMProfileRegistry, RoutingHint


def _mock_settings():
    mock = MagicMock()
    mock.llm.max_tokens = 4096
    mock.llm.temperature = 0.7
    mock.llm.model = "test-model"
    mock.llm.cheap_model = "test-fallback"
    mock.llm.cost_limit_per_report = 0
    mock.llm.api_key = "test-key"
    mock.llm.base_url = "https://test.example.com"
    mock.llm.top_p = 1.0
    mock.llm.frequency_penalty = 0.0
    mock.llm.presence_penalty = 0.0
    return mock


def _make_registry():
    strong = LLMProfile(name="strong", api_key="sk-strong", base_url="https://strong.api/v1", model="gpt-4o", fallback_model="gpt-4o-mini")
    fast = LLMProfile(name="fast", api_key="sk-fast", base_url="https://fast.api/v1", model="gpt-4o-mini", fallback_model="gpt-3.5-turbo")
    default = LLMProfile(name="migrated", api_key="sk-default", base_url="https://default.api/v1", model="test-model", fallback_model="test-fallback")
    return LLMProfileRegistry(profiles={"strong": strong, "fast": fast, "migrated": default}, default_profile="migrated")


class TestRoutingHintLegacyPath:
    @pytest.mark.asyncio
    async def test_no_hint_no_router_uses_settings(self):
        with patch("src.core.llm_client.settings", _mock_settings()):
            with patch("src.core.llm_client._call_llm_api", new_callable=AsyncMock) as mock_api:
                mock_api.return_value = {"choices": [{"message": {"content": "ok"}}], "usage": {}}
                from src.core.llm_client import call_llm
                result = await call_llm(prompt="test")
                assert result["success"] is True
                call_kwargs = mock_api.call_args[1]
                assert call_kwargs["model"] == "test-model"
                assert call_kwargs["api_key"] == "test-key"

    @pytest.mark.asyncio
    async def test_hint_none_uses_settings(self):
        with patch("src.core.llm_client.settings", _mock_settings()):
            with patch("src.core.llm_client._call_llm_api", new_callable=AsyncMock) as mock_api:
                mock_api.return_value = {"choices": [{"message": {"content": "ok"}}], "usage": {}}
                from src.core.llm_client import call_llm
                result = await call_llm(prompt="test", routing_hint=None)
                assert result["success"] is True
                call_kwargs = mock_api.call_args[1]
                assert call_kwargs["model"] == "test-model"


class TestRoutingHintWithRouter:
    @pytest.mark.asyncio
    async def test_hint_routes_to_profile(self):
        registry = _make_registry()
        with patch("src.core.llm_client.settings", _mock_settings()):
            from src.core.llm_client import init_llm_infrastructure, _router, _client_pool
            init_llm_infrastructure(registry)
            with patch("src.core.llm_client._call_llm_api", new_callable=AsyncMock) as mock_api:
                mock_api.return_value = {"choices": [{"message": {"content": "routed"}}], "usage": {}}
                from src.core.llm_client import call_llm
                hint = RoutingHint(action="deep_analysis")
                result = await call_llm(prompt="test", routing_hint=hint)
                assert result["success"] is True
                call_kwargs = mock_api.call_args[1]
                assert call_kwargs["model"] == "gpt-4o"
                assert call_kwargs["api_key"] == "sk-strong"

    @pytest.mark.asyncio
    async def test_hint_with_explicit_profile_name(self):
        registry = _make_registry()
        with patch("src.core.llm_client.settings", _mock_settings()):
            from src.core.llm_client import init_llm_infrastructure
            init_llm_infrastructure(registry)
            with patch("src.core.llm_client._call_llm_api", new_callable=AsyncMock) as mock_api:
                mock_api.return_value = {"choices": [{"message": {"content": "fast"}}], "usage": {}}
                from src.core.llm_client import call_llm
                hint = RoutingHint(profile_name="fast")
                result = await call_llm(prompt="test", routing_hint=hint)
                assert result["success"] is True
                call_kwargs = mock_api.call_args[1]
                assert call_kwargs["model"] == "gpt-4o-mini"
                assert call_kwargs["api_key"] == "sk-fast"

    @pytest.mark.asyncio
    async def test_hint_unmatched_falls_back_to_default_profile(self):
        registry = _make_registry()
        with patch("src.core.llm_client.settings", _mock_settings()):
            from src.core.llm_client import init_llm_infrastructure
            init_llm_infrastructure(registry)
            with patch("src.core.llm_client._call_llm_api", new_callable=AsyncMock) as mock_api:
                mock_api.return_value = {"choices": [{"message": {"content": "default"}}], "usage": {}}
                from src.core.llm_client import call_llm
                hint = RoutingHint(action="unknown_action")
                result = await call_llm(prompt="test", routing_hint=hint)
                assert result["success"] is True
                call_kwargs = mock_api.call_args[1]
                assert call_kwargs["model"] == "test-model"
                assert call_kwargs["api_key"] == "sk-default"

    @pytest.mark.asyncio
    async def test_hint_with_no_router_falls_back_to_settings(self):
        with patch("src.core.llm_client.settings", _mock_settings()):
            from src.core.llm_client import _router
            import src.core.llm_client as mod
            orig = mod._router
            mod._router = None
            try:
                with patch("src.core.llm_client._call_llm_api", new_callable=AsyncMock) as mock_api:
                    mock_api.return_value = {"choices": [{"message": {"content": "legacy"}}], "usage": {}}
                    from src.core.llm_client import call_llm
                    hint = RoutingHint(action="deep_analysis")
                    result = await call_llm(prompt="test", routing_hint=hint)
                    assert result["success"] is True
                    call_kwargs = mock_api.call_args[1]
                    assert call_kwargs["model"] == "test-model"
            finally:
                mod._router = orig

    @pytest.mark.asyncio
    async def test_explicit_params_override_hint(self):
        registry = _make_registry()
        with patch("src.core.llm_client.settings", _mock_settings()):
            from src.core.llm_client import init_llm_infrastructure
            init_llm_infrastructure(registry)
            with patch("src.core.llm_client._call_llm_api", new_callable=AsyncMock) as mock_api:
                mock_api.return_value = {"choices": [{"message": {"content": "override"}}], "usage": {}}
                from src.core.llm_client import call_llm
                hint = RoutingHint(profile_name="fast")
                result = await call_llm(prompt="test", routing_hint=hint, model="my-custom-model", api_key="my-key")
                assert result["success"] is True
                call_kwargs = mock_api.call_args[1]
                assert call_kwargs["model"] == "my-custom-model"
                assert call_kwargs["api_key"] == "my-key"
                assert call_kwargs["base_url"] == "https://fast.api/v1"

    @pytest.mark.asyncio
    async def test_hint_fills_non_overridden_fields(self):
        registry = _make_registry()
        with patch("src.core.llm_client.settings", _mock_settings()):
            from src.core.llm_client import init_llm_infrastructure
            init_llm_infrastructure(registry)
            with patch("src.core.llm_client._call_llm_api", new_callable=AsyncMock) as mock_api:
                mock_api.return_value = {"choices": [{"message": {"content": "ok"}}], "usage": {}}
                from src.core.llm_client import call_llm
                hint = RoutingHint(profile_name="fast")
                result = await call_llm(prompt="test", routing_hint=hint, model="my-custom-model")
                assert result["success"] is True
                call_kwargs = mock_api.call_args[1]
                assert call_kwargs["model"] == "my-custom-model"
                assert call_kwargs["api_key"] == "sk-fast"
                assert call_kwargs["base_url"] == "https://fast.api/v1"


class TestInitLlmInfrastructure:
    def test_init_creates_router_and_pool(self):
        registry = _make_registry()
        from src.core.llm_client import init_llm_infrastructure, _router, _client_pool
        import src.core.llm_client as mod
        init_llm_infrastructure(registry)
        assert mod._router is not None
        assert mod._client_pool is not None
