---
name: policy_analysis
description: "Policy analysis: policy impact assessment/transmission channels/winners-losers/scenario analysis"
version: "1.0"
categories:
  - analysis
priority: llm
keywords: []
aliases: []
capabilities:
  - analyze
action_rules:
  - pattern: ".*"
    actions: [analyze]
action_param_map:
  analyze: {}
supports_topic_fallback: false
is_intrinsic: false
skill_type: standard
aspect_coverage:
  - Policy Environment
---
