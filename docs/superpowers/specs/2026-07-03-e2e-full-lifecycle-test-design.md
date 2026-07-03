# E2E Full Lifecycle Test Design

> Date: 2026-07-03
> Status: Approved
> Strategy: Real LLM calls, API-level E2E, layered scenario testing

## 1. Overview

End-to-end test suite covering the full research report lifecycle: user request → dialogue → framework confirmation → agent execution → report generation → preview → revision → quality review → finalization/export.

Two research topics are tested to cover different complexity levels:
- **中国新能源汽车市场** (broad industry research, multi-section framework)
- **比亚迪财务分析** (focused financial analysis, fewer sections)

## 2. Architecture

```
tests/e2e/
├── conftest.py                    # Shared fixtures: TestClient, LLM config, helpers
├── test_e2e_full_lifecycle.py     # Phase 1: Normal full lifecycle
├── test_e2e_state_machine.py      # Phase 2: State machine boundary
├── test_e2e_revision_loop.py      # Phase 3: Revision loop
├── test_e2e_error_recovery.py     # Phase 4: Error recovery
├── test_e2e_concurrency.py        # Phase 5: Concurrency & race conditions
└── helpers/
    ├── api_client.py              # API call wrapper client
    ├── assertion_helpers.py       # Custom assertions
    └── wait_helpers.py            # Async wait/poll utilities
```

## 3. API Client

A thin wrapper around `httpx.AsyncClient` that encapsulates all Zensers API calls:

```python
class ZensersClient:
    async def start_research(user_input, user_id, llm_config) -> dict
    async def quick_start(user_input, template_id, ...) -> dict
    async def interact(session_id, step, response, llm_config) -> dict
    async def pause_research(task_id) -> dict
    async def resume_research(task_id) -> dict
    async def cancel_research(task_id) -> dict
    async def get_status(task_id) -> dict
    async def get_preview(task_id, format) -> dict
    async def get_sections(task_id) -> dict
    async def quality_action(session_id, action, data) -> dict
    async def quality_state(session_id) -> dict
    async def feedback(session_id, action, section, adjustment) -> dict
    async def revise_sections(task_id, aspects, adjustment) -> dict
    async def download(task_id) -> httpx.Response
    async def wait_for_completion(task_id, timeout=600, poll_interval=5) -> dict
```

## 4. Shared Fixtures (conftest.py)

- `api_client`: ZensersClient instance using httpx.AsyncClient against FastAPI TestClient
- `llm_config`: Loaded from .env or environment variables
- `cleanup_sessions`: Auto-cleanup fixture that removes test sessions after each test
- `new_energy_topic` / `byd_topic`: Predefined topic fixtures

## 5. Phase 1: Normal Full Lifecycle

### 5.1 New Energy Vehicle Full Flow

API call chain:
1. `POST /api/v1/research/start` → session_id
2. `POST /api/v1/research/interact` (step=0, mode=chat) → LLM identifies intent
3. `POST /api/v1/research/interact` (step=0, mode=framework) → confirm framework
4. Poll `GET /api/v1/research/{task_id}/status` → wait for completion
5. `GET /api/v1/research/preview/{task_id}` → get preview
6. Verify preview has sections, HTML content
7. `POST /api/v1/research/quality/action` (accept) → confirm quality
8. `GET /api/v1/download/{task_id}` → download docx
9. Verify docx file exists and has content

Assertions:
- session_id returned from start
- State transitions: understanding → framework → executing → completed
- Preview HTML contains all framework sections
- Quality state exists with overall_score
- Download returns valid document file

### 5.2 BYD Financial Analysis Quick-Start Flow

API call chain:
1. `POST /api/v1/research/quick-start` with template_id → session_id
2. Poll status → wait for completion
3. `GET /api/v1/research/preview/{task_id}` → get preview
4. `POST /api/v1/research/quality/action` (accept)
5. `GET /api/v1/download/{task_id}` → download docx

Assertions:
- Quick-start returns valid session_id
- Execution completes successfully
- Preview and download work

## 6. Phase 2: State Machine Boundary

| Scenario | Input State | Action | Expected |
|----------|------------|--------|----------|
| 2.1 Invalid transition | UNDERSTANDING | Try to complete | Error / rejected |
| 2.2 Heavy action in EXECUTING | EXECUTING | modify_research | Downgraded to lightweight |
| 2.3 Framework confirm while PAUSED | PAUSED | confirm framework | Must resume first |
| 2.4 Resume from CANCELLED | CANCELLED | resume | Not allowed |
| 2.5 Double confirm | FRAMEWORK_CONFIRM | confirm twice | Idempotent |

## 7. Phase 3: Revision Loop

| Scenario | Flow | Verification |
|----------|------|-------------|
| 3.1 Single section revise | quality_action(revise, section) → recheck → accept | Section updated, quality improved |
| 3.2 Multi-section batch revise | quality_action(revise, [s1, s2]) → recheck | Both sections updated |
| 3.3 Revision still fails loop | revise → recheck → still issues → revise again | Loop continues until pass or max_rounds |
| 3.4 Version rollback | revise → quality_action(rollback) → verify | Content restored to previous version |
| 3.5 Max revision rounds | 10 revision rounds on same issue | max_retries_reached state |

## 8. Phase 4: Error Recovery

| Scenario | Flow | Verification |
|----------|------|-------------|
| 4.1 Pause & resume | start → executing → pause → resume | Execution continues from checkpoint |
| 4.2 Cancel during execution | start → executing → cancel | Session enters cancelled, resources cleaned |
| 4.3 SSE disconnect fallback | start → disconnect SSE → poll status | Can still get progress via polling |
| 4.4 Server restart recovery | session active → simulate restart → recover | Session state preserved on disk |

## 9. Phase 5: Concurrency & Race Conditions

| Scenario | Flow | Verification |
|----------|------|-------------|
| 5.1 Concurrent quality actions | 2 threads: quality_action(accept) + quality_action(revise) | Serialized by lock, no corruption |
| 5.2 Concurrent section revisions | Revise section A + revise section B simultaneously | Both complete independently |
| 5.3 Interact during execution | Send chat while research executing | Returns appropriate response (not crash) |

## 10. Technical Decisions

1. **Real LLM calls**: All LLM interactions use real API via `.env` configuration
2. **Timeout**: 10 minutes per test scenario (real LLM + agent execution)
3. **Idempotent cleanup**: Each test creates independent session, cleaned up after
4. **SSE wait**: Async polling via `/api/v1/research/{task_id}/status` instead of SSE streaming
5. **Markers**: `@pytest.mark.e2e` + `@pytest.mark.slow` for selective execution
6. **Test isolation**: Each test gets fresh session, no cross-test dependencies
7. **Retry**: Network/LLM flaky failures get 1 retry with `@pytest.mark.flaky`
8. **LLM requirement per phase**:
   - Phase 1: Real LLM (full lifecycle requires LLM for dialogue + agent execution)
   - Phase 2: No LLM needed (state machine transitions are deterministic, manipulate session directly)
   - Phase 3: Real LLM (revision requires LLM to generate revised content)
   - Phase 4: Real LLM for pause/resume scenarios; no LLM for SSE disconnect polling
   - Phase 5: Real LLM (concurrent operations need real execution paths)

## 11. Execution

```bash
# Run all E2E tests
pytest tests/e2e/ -m e2e --timeout=600

# Run single phase
pytest tests/e2e/test_e2e_full_lifecycle.py -m e2e

# Run with specific LLM config
LLM_PROVIDER=openai LLM_MODEL=gpt-4o pytest tests/e2e/ -m e2e
```

## 12. Success Criteria

- Phase 1: Both topics complete full lifecycle without errors
- Phase 2: All invalid state transitions properly rejected
- Phase 3: Revision loop works through all scenarios including rollback
- Phase 4: Error recovery preserves data integrity
- Phase 5: No race conditions cause data corruption
