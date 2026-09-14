"""Test: _llm_converse() streaming branch integration"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock


@pytest.fixture
def mock_deps():
    deps = {}
    sm = MagicMock()
    sm.get.return_value = {
        "research_context": {},
        "conversation_history": [],
        "llm_config": {},
    }
    deps["session_manager"] = sm

    ms = MagicMock()
    ms.llm.max_tokens = 4096
    ms.llm.temperature = 0.7
    ms.llm.model = "test-model"
    ms.llm.cheap_model = "test-fallback"
    ms.llm.cost_limit_per_report = 0
    ms.llm.api_key = "test-key"
    ms.llm.base_url = "https://test.example.com"
    ms.llm.top_p = 1.0
    ms.llm.frequency_penalty = 0.0
    ms.llm.presence_penalty = 0.0
    deps["settings"] = ms

    pm = MagicMock()
    profile = MagicMock()
    profile.get_full_prompt.return_value = "You are a helpful assistant."
    pm.load_profile.return_value = profile
    deps["prompt_manager"] = pm
    deps["pm_instance"] = MagicMock()
    deps["pm_instance"].load_profile.return_value = profile

    deps["SessionStreamer"] = MagicMock()
    ts = MagicMock()
    ts.TOOL_DEFINITIONS = []
    deps["tool_set"] = ts
    return deps


class TestLlmConverseStreamingBranch:
    def test_imports_call_llm_stream(self):
        from src.api.research_api import _ThinkTagFilter
        from src.core.llm_client import call_llm_stream, call_llm
        assert callable(call_llm_stream)
        assert callable(call_llm)
        assert callable(_ThinkTagFilter)

    @pytest.mark.asyncio
    async def test_stream_first_iteration_calls_stream_api(self, mock_deps):
        deps = mock_deps

        test_tokens = ['{"message": "Hello', '", "action": "continue_chat", "tool_call": null}', '']

        async def _mock_stream(*args, **kwargs):
            for t in test_tokens:
                yield t

        with patch("src.api.research_api.session_manager", deps["session_manager"]):
            with patch("src.api.research_api.PromptManager") as pm_cls:
                pm_cls.get_instance.return_value = deps["pm_instance"]
                with patch("src.core.session_streamer.SessionStreamer", deps["SessionStreamer"]):
                    with patch("src.api.research_api.call_llm_stream", new=_mock_stream):
                        with patch("src.api.research_api.call_llm", new_callable=AsyncMock) as mock_call_llm:
                            with patch("src.config.settings", deps["settings"]):
                                from src.api.research_api import ResearchAPI
                                api = ResearchAPI()
                                api._tool_set = deps["tool_set"]
                                api._loop_cancel_flags = {}

                                result = await api._llm_converse("test_ses", "hello")

                                mock_call_llm.assert_not_called()
                                assert result["status"] == "done"
                                assert "message" in result

    @pytest.mark.asyncio
    async def test_stream_routing_thinking_tokens(self, mock_deps):
        """When tokens contain think tags, push_chat_thinking is called for think content."""
        deps = mock_deps
        mock_streamer = MagicMock()
        deps["SessionStreamer"] = mock_streamer

        from src.api.research_api import _THINK_OPEN, _THINK_CLOSE
        test_tokens = [_THINK_OPEN + "thinking" + _THINK_CLOSE + '{"message": "Hi", "action": "continue_chat", "tool_call": null}']

        async def _mock_stream(*args, **kwargs):
            for t in test_tokens:
                yield t

        with patch("src.api.research_api.session_manager", deps["session_manager"]):
            with patch("src.api.research_api.PromptManager") as pm_cls:
                pm_cls.get_instance.return_value = deps["pm_instance"]
                with patch("src.core.session_streamer.SessionStreamer", mock_streamer):
                    with patch("src.api.research_api.call_llm_stream", new=_mock_stream):
                        with patch("src.api.research_api.call_llm", new_callable=AsyncMock):
                            with patch("src.config.settings", deps["settings"]):
                                from src.api.research_api import ResearchAPI
                                api = ResearchAPI()
                                api._tool_set = deps["tool_set"]
                                api._loop_cancel_flags = {}

                                result = await api._llm_converse("test_ses", "hello")

                                mock_streamer.push_chat_thinking.assert_called()
                                mock_streamer.push_chat_token.assert_called()

    @pytest.mark.asyncio
    async def test_stream_failure_degrades_to_call_llm(self, mock_deps):
        deps = mock_deps

        async def _mock_call_llm(*args, **kwargs):
            return {
                "success": True,
                "content": '{"message": "fallback", "action": "continue_chat", "tool_call": null}',
                "model": "test-model",
                "usage": {},
            }

        with patch("src.api.research_api.session_manager", deps["session_manager"]):
            with patch("src.api.research_api.PromptManager") as pm_cls:
                pm_cls.get_instance.return_value = deps["pm_instance"]
                with patch("src.core.session_streamer.SessionStreamer", deps["SessionStreamer"]):
                    with patch("src.api.research_api.call_llm_stream",
                               side_effect=Exception("stream failed")):
                        with patch("src.api.research_api.call_llm", new=_mock_call_llm):
                            with patch("src.config.settings", deps["settings"]):
                                from src.api.research_api import ResearchAPI
                                api = ResearchAPI()
                                api._tool_set = deps["tool_set"]
                                api._loop_cancel_flags = {}

                                result = await api._llm_converse("test_ses", "hello")
                                assert result["message"] == "fallback"
                                assert result["action"] == "continue_chat"

    @pytest.mark.asyncio
    async def test_empty_stream_falls_back_before_intent_parse(self, mock_deps):
        """A cleanly-closed empty stream must not become an empty intent."""
        deps = mock_deps

        async def _empty_stream(*args, **kwargs):
            if False:
                yield ""

        async def _mock_call_llm(*args, **kwargs):
            return {
                "success": True,
                "content": '{"message": "fallback", "action": "continue_chat", "tool_call": null}',
            }

        with patch("src.api.research_api.session_manager", deps["session_manager"]):
            with patch("src.api.research_api.PromptManager") as pm_cls:
                pm_cls.get_instance.return_value = deps["pm_instance"]
                with patch("src.core.session_streamer.SessionStreamer", deps["SessionStreamer"]):
                    with patch("src.api.research_api.call_llm_stream", new=_empty_stream):
                        with patch("src.api.research_api.call_llm", new_callable=AsyncMock,
                                   side_effect=_mock_call_llm) as mock_call_llm:
                            with patch("src.config.settings", deps["settings"]):
                                from src.api.research_api import ResearchAPI
                                api = ResearchAPI()
                                api._tool_set = deps["tool_set"]
                                api._loop_cancel_flags = {}

                                result = await api._llm_converse("test_ses", "hello")

                                assert result["message"] == "fallback"
                                assert mock_call_llm.call_count == 1

    @pytest.mark.asyncio
    async def test_empty_stream_failed_fallback_is_called_once(self, mock_deps):
        """A failed non-stream degradation must not be retried by the outer handler."""
        deps = mock_deps

        async def _empty_stream(*args, **kwargs):
            if False:
                yield ""

        with patch("src.api.research_api.session_manager", deps["session_manager"]):
            with patch("src.api.research_api.PromptManager") as pm_cls:
                pm_cls.get_instance.return_value = deps["pm_instance"]
                with patch("src.core.session_streamer.SessionStreamer", deps["SessionStreamer"]):
                    with patch("src.api.research_api.call_llm_stream", new=_empty_stream):
                        with patch("src.api.research_api.call_llm", new_callable=AsyncMock,
                                   return_value={"success": False, "error": "empty_content"}) as mock_call_llm:
                            with patch("src.config.settings", deps["settings"]):
                                from src.api.research_api import ResearchAPI
                                api = ResearchAPI()
                                api._tool_set = deps["tool_set"]
                                api._loop_cancel_flags = {}

                                result = await api._llm_converse("test_ses", "hello")

                                assert result["action"] == "continue_chat"
                                assert mock_call_llm.call_count == 1

    @pytest.mark.asyncio
    async def test_push_chat_token_not_called_on_degraded_path(self, mock_deps):
        deps = mock_deps
        mock_streamer = MagicMock()
        deps["SessionStreamer"] = mock_streamer

        async def _mock_call_llm(*args, **kwargs):
            return {
                "success": True,
                "content": '{"message": "degraded", "action": "continue_chat", "tool_call": null}',
                "model": "test-model",
                "usage": {},
            }

        with patch("src.api.research_api.session_manager", deps["session_manager"]):
            with patch("src.api.research_api.PromptManager") as pm_cls:
                pm_cls.get_instance.return_value = deps["pm_instance"]
                with patch("src.core.session_streamer.SessionStreamer", mock_streamer):
                    with patch("src.api.research_api.call_llm_stream",
                               side_effect=Exception("stream failed")):
                        with patch("src.api.research_api.call_llm", new=_mock_call_llm):
                            with patch("src.config.settings", deps["settings"]):
                                from src.api.research_api import ResearchAPI
                                api = ResearchAPI()
                                api._tool_set = deps["tool_set"]
                                api._loop_cancel_flags = {}

                                await api._llm_converse("test_ses", "hello")
                                mock_streamer.push_chat_token.assert_not_called()

    @pytest.mark.asyncio
    async def test_none_llm_response_is_reported_without_none_type_error(self, mock_deps):
        """A provider returning None must not be converted into result.get()."""
        deps = mock_deps

        with patch("src.api.research_api.session_manager", deps["session_manager"]):
            with patch("src.api.research_api.PromptManager") as pm_cls:
                pm_cls.get_instance.return_value = deps["pm_instance"]
                with patch("src.core.session_streamer.SessionStreamer", deps["SessionStreamer"]):
                    with patch("src.api.research_api.call_llm_stream",
                               side_effect=Exception("stream unavailable")):
                        with patch("src.api.research_api.call_llm", new_callable=AsyncMock,
                                   return_value=None):
                            with patch("src.config.settings", deps["settings"]):
                                from src.api.research_api import ResearchAPI
                                api = ResearchAPI()
                                api._tool_set = deps["tool_set"]
                                api._loop_cancel_flags = {}

                                result = await api._llm_converse("test_ses", "hello")

                                assert result["action"] == "continue_chat"
                                assert "重新描述" in result["message"]

    @pytest.mark.asyncio
    async def test_non_first_iteration_uses_call_llm(self, mock_deps):
        deps = mock_deps

        async def _mock_stream(*args, **kwargs):
            yield '{"message": "Let me search", "action": "continue_chat", ' \
                  '"tool_call": {"name": "web_search", "arguments": {"query": "test"}}}'

        async def _mock_call_llm(*args, **kwargs):
            return {
                "success": True,
                "content": '{"message": "search done", "action": "continue_chat", "tool_call": null}',
                "model": "test-model",
                "usage": {},
            }

        mock_tool_set = MagicMock()
        mock_tool_set.TOOL_DEFINITIONS = []
        mock_tool_set.execute_tool = AsyncMock(return_value={"success": True, "data": "test result"})

        with patch("src.api.research_api.session_manager", deps["session_manager"]):
            with patch("src.api.research_api.PromptManager") as pm_cls:
                pm_cls.get_instance.return_value = deps["pm_instance"]
                with patch("src.core.session_streamer.SessionStreamer", deps["SessionStreamer"]):
                    with patch("src.api.research_api.call_llm_stream", new=_mock_stream):
                        with patch("src.api.research_api.call_llm", new=_mock_call_llm):
                            with patch("src.config.settings", deps["settings"]):
                                from src.api.research_api import ResearchAPI
                                api = ResearchAPI()
                                api._tool_set = mock_tool_set
                                api._loop_cancel_flags = {}
                                api._JSON_OUTPUT_SCHEMA = "{}"

                                result = await api._llm_converse("test_ses", "hello")
                                # Tool chains are intentionally continued in
                                # the background after the first search.
                                assert result["status"] == "processing"
                                assert result["message"] == "Let me search"
                                mock_tool_set.execute_tool.assert_awaited_once()
