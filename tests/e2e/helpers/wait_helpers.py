# -*- coding: utf-8 -*-
import asyncio
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


async def poll_until(
    check_fn: Callable,
    timeout: float = 600,
    poll_interval: float = 5,
    description: str = "condition",
) -> bool:
    elapsed = 0.0
    while elapsed < timeout:
        try:
            result = await check_fn() if asyncio.iscoroutinefunction(check_fn) else check_fn()
            if result:
                return True
        except Exception as e:
            logger.debug(f"poll_until({description}) check raised: {e}")
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
    logger.warning(f"poll_until({description}) timed out after {elapsed}s")
    return False


async def poll_status_until(
    client,
    task_id: str,
    target_status: str,
    timeout: float = 600,
    poll_interval: float = 5,
) -> dict:
    elapsed = 0.0
    while elapsed < timeout:
        status = await client.get_status(task_id)
        cur = status.get("status", "unknown")
        if cur == target_status:
            return status
        if cur in ("failed", "error", "cancelled") and target_status not in ("failed", "error", "cancelled"):
            return status
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
    return {"status": "timeout", "task_id": task_id}
