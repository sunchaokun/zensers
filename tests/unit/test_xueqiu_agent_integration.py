"""
XueqiuSkill GenericAgent 集成测试 — Phase 3

测试覆盖：
1. _infer_xueqiu_actions 对标准 A 股代码返回 quote + kline
2. _infer_xueqiu_actions 对非标准代码返回 search_and_quote
3. _infer_xueqiu_actions 对中文公司名返回 search_and_quote
4. _infer_xueqiu_actions 对竞争类 aspect 额外添加 hot_stocks
5. _fetch_structured_data 中 skill_name="xueqiu" 走 xueqiu 分支
6. _fetch_structured_data 中 xueqiu topic fallback（symbols 为空时用 topic）
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


class TestInferXueqiuActions:
    @pytest.fixture
    def agent(self):
        from src.core.agents.generic_agent import GenericAgent
        config = {
            "agent_id": "test_xueqiu_agent",
            "agent_type": "research",
            "name": "Test Xueqiu Agent",
            "skills": ["xueqiu"],
            "category": "research",
        }
        return GenericAgent(config)

    def test_a_share_code_returns_quote(self, agent):
        actions = agent._infer_xueqiu_actions("财务分析", "002594")
        assert "quote" in actions

    def test_a_share_code_with_financial_aspect_adds_kline(self, agent):
        actions = agent._infer_xueqiu_actions("估值分析", "SH600519")
        assert "quote" in actions
        assert "kline" in actions

    def test_non_standard_code_returns_search_and_quote(self, agent):
        actions = agent._infer_xueqiu_actions("估值分析", "00700")
        assert actions == ["search_and_quote"]

    def test_chinese_name_returns_search_and_quote(self, agent):
        actions = agent._infer_xueqiu_actions("估值分析", "腾讯控股")
        assert actions == ["search_and_quote"]

    def test_us_stock_returns_search_and_quote(self, agent):
        actions = agent._infer_xueqiu_actions("估值分析", "AAPL")
        assert actions == ["search_and_quote"]

    def test_competitive_aspect_adds_hot_stocks(self, agent):
        actions = agent._infer_xueqiu_actions("竞争格局", "SH600519")
        assert "hot_stocks" in actions

    def test_default_action_is_quote(self, agent):
        actions = agent._infer_xueqiu_actions("公司概况", "SH600519")
        assert "quote" in actions

    def test_no_financials_action(self, agent):
        actions = agent._infer_xueqiu_actions("财务分析", "SH600519")
        assert "financials" not in actions
        assert "company_info" not in actions


class TestFetchStructuredDataXueqiu:
    @pytest.mark.asyncio
    async def test_xueqiu_topic_fallback_for_non_a_share(self):
        from src.core.agents.generic_agent import GenericAgent
        from src.skills.analysis.xueqiu_skill import XueqiuSkill
        XueqiuSkill._memory_cache.clear()
        config = {
            "agent_id": "test_xueqiu_fetch",
            "agent_type": "research",
            "name": "Test Fetch Agent",
            "skills": ["xueqiu"],
            "category": "research",
            "context": {"entities": []},
        }
        agent = GenericAgent(config)
        agent._skill_registry = MagicMock()

        xueqiu_skill = MagicMock(spec=XueqiuSkill)
        xueqiu_skill.execute = AsyncMock(return_value={
            "success": True, "data": {"search": {"symbol": "00700"}, "quote": {"current": 380.0}},
            "content": "腾讯控股(00700): 当前价 380.0", "source": "xueqiu",
        })
        agent._skill_registry.get.return_value = xueqiu_skill

        with patch.object(agent, '_extract_stock_symbol', return_value=None), \
             patch.object(agent, '_resolve_company_to_code', return_value=None):
            result = await agent._fetch_structured_data(
                xueqiu_skill, "腾讯控股估值分析", "估值分析", skill_name="xueqiu"
            )
        assert len(result.get("data_points", [])) > 0 or result.get("sources", []) != []
