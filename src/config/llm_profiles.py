from dataclasses import dataclass, field
from typing import Optional, Dict, List


@dataclass
class LLMProfile:
    name: str
    display_name: str = ""
    provider: str = "openai"
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    max_context_tokens: int = 128000
    cost_limit_per_call: float = 0.0
    is_default: bool = False
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""


@dataclass
class LLMProfileRegistry:
    profiles: Dict[str, LLMProfile] = field(default_factory=dict)
    default_profile: str = "fast"
    fallback_chain: List[str] = field(default_factory=lambda: ["strong", "fast", "local"])
    fixed_agent_routing: Dict[str, str] = field(default_factory=dict)
    action_routing: Dict[str, str] = field(default_factory=dict)


@dataclass
class RoutingHint:
    agent_type: Optional[str] = None
    action: Optional[str] = None
    profile_name: Optional[str] = None
    force_profile: bool = False
