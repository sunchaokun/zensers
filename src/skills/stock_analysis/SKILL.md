---
name: stock_analysis
description: "Deep financial analysis: financial health/growth trend/valuation/investment value assessment"
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
  - Financial Analysis
  - Valuation Analysis
  - Investment Advice
  - Company Analysis
---
