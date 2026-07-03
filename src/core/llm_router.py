from src.config.llm_profiles import LLMProfile, LLMProfileRegistry, RoutingHint


class LLMRouter:
    REASONING_KEYWORDS = {
        "analyze", "analysis", "generate", "write", "review", "plan",
        "synthesize", "reason", "evaluate", "assess", "judge", "critique",
        "summarize", "interpret", "recommend", "decide", "compare",
    }
    UTILITY_KEYWORDS = {
        "search", "scrape", "format", "translate", "extract", "parse",
        "classify", "count", "lookup", "fetch", "validate", "check",
        "embed", "tokenize", "convert",
    }

    def __init__(self, registry: LLMProfileRegistry):
        self.registry = registry

    def resolve(self, hint: RoutingHint) -> LLMProfile:
        if hint.profile_name:
            profile = self.registry.profiles.get(hint.profile_name)
            if profile and (hint.force_profile or profile.enabled):
                return profile

        if hint.agent_type:
            profile_name = self.registry.fixed_agent_routing.get(hint.agent_type)
            if profile_name:
                profile = self.registry.profiles.get(profile_name)
                if profile and profile.enabled:
                    return profile

        if hint.action:
            profile_name = self.registry.action_routing.get(hint.action)
            if profile_name:
                profile = self.registry.profiles.get(profile_name)
                if profile and profile.enabled:
                    return profile

        if hint.action:
            action_lower = hint.action.lower()
            if any(kw in action_lower for kw in self.REASONING_KEYWORDS):
                for name in ["strong", "default"]:
                    profile = self.registry.profiles.get(name)
                    if profile and profile.enabled:
                        return profile
            elif any(kw in action_lower for kw in self.UTILITY_KEYWORDS):
                for name in ["fast", "default"]:
                    profile = self.registry.profiles.get(name)
                    if profile and profile.enabled:
                        return profile

        default = self.registry.profiles.get(self.registry.default_profile)
        if default and default.enabled:
            return default

        for profile in self.registry.profiles.values():
            if profile.enabled:
                return profile

        raise RuntimeError("No enabled LLM profile available")
