"""Atomic, append-only phase boundary manifest for research tasks."""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_EVENTS = {
    "PHASE_START", "PHASE_INPUT", "PHASE_OUTPUT",
    "CHECKPOINT_SAVED", "PHASE_COMPLETE", "PHASE_FAILED",
}


class PhaseManifestStore:
    """Persist auditable phase events without coupling to execution control."""

    _locks: Dict[str, threading.Lock] = {}
    _locks_guard = threading.Lock()

    def __init__(
        self, task_id: str, session_id: str, root: Path = Path("data"),
        run_id: Optional[str] = None,
    ) -> None:
        self.task_id = str(task_id)
        self.session_id = str(session_id)
        self.run_id = str(run_id or "")
        self.path = (Path(root) / self.task_id / "diagnostic_manifest.json").resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

        with self._locks_guard:
            self._locks.setdefault(str(self.path), threading.Lock())
        with self._locks_guard:
            lock = self._locks[str(self.path)]
        with lock:
            if not self.path.exists():
                self._write({
                    "session_id": self.session_id,
                    "task_id": self.task_id,
                    "run_id": self.run_id,
                    "phases": [],
                })

    def record(self, event: str, *, phase: str = "", batch_id: str = "",
               agent_id: str = "", section_id: str = "",
               checkpoint_id: str = "", **details: Any) -> Dict[str, Any]:
        if event not in _EVENTS:
            raise ValueError(f"Unsupported phase event: {event}")
        if not phase:
            raise ValueError("phase is required for a boundary event")

        item = {
            "event": event,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "phase": phase,
            "batch_id": batch_id,
            "agent_id": agent_id,
            "section_id": section_id,
            "checkpoint_id": checkpoint_id,
            **details,
        }
        with self._locks_guard:
            lock = self._locks[str(self.path)]
        with lock:
            manifest = self._read()
            manifest.setdefault("phases", []).append(item)
            self._write(manifest)
        logger.info(
            "%s session_id=%s task_id=%s run_id=%s phase=%s batch_id=%s agent_id=%s section_id=%s checkpoint_id=%s",
            event, self.session_id, self.task_id, self.run_id, phase,
            batch_id, agent_id, section_id, checkpoint_id,
        )
        return item

    def _read(self) -> Dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"session_id": self.session_id, "task_id": self.task_id,
                    "run_id": self.run_id, "phases": []}

    def _write(self, data: Dict[str, Any]) -> None:
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.path)
