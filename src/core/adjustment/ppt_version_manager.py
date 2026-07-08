import json
import os
import shutil
from datetime import datetime
from typing import Dict, List, Optional


class PptVersionManager:

    def __init__(self, revisions_dir: str, max_versions: int = 10):
        self._revisions_dir = revisions_dir
        self._max_versions = max_versions
        self._version_counters: Dict[str, int] = {}

    def create_snapshot(self, task_id: str, pptx_path: str,
                        revision_level: str, user_message: str) -> int:
        task_dir = os.path.join(self._revisions_dir, task_id)
        os.makedirs(task_dir, exist_ok=True)

        version = self._version_counters.get(task_id, 0) + 1
        self._version_counters[task_id] = version

        snap_path = os.path.join(task_dir, f"v{version}.pptx")
        shutil.copy2(pptx_path, snap_path)

        self._append_metadata(task_dir, {
            "version": version,
            "timestamp": datetime.now().isoformat(),
            "revision_level": revision_level,
            "user_message": user_message,
        })

        self._enforce_max_versions(task_id, task_dir)
        return version

    def rollback(self, task_id: str, version: int, active_pptx_path: str) -> None:
        task_dir = os.path.join(self._revisions_dir, task_id)
        snap_path = os.path.join(task_dir, f"v{version}.pptx")
        if not os.path.exists(snap_path):
            raise ValueError(f"Version {version} not found for task {task_id}")
        shutil.copy2(snap_path, active_pptx_path)

    def list_versions(self, task_id: str) -> List[Dict]:
        task_dir = os.path.join(self._revisions_dir, task_id)
        meta_path = os.path.join(task_dir, "metadata.json")
        if not os.path.exists(meta_path):
            return []
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _append_metadata(self, task_dir: str, entry: Dict) -> None:
        meta_path = os.path.join(task_dir, "metadata.json")
        metadata = []
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        metadata.append(entry)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

    def _enforce_max_versions(self, task_id: str, task_dir: str) -> None:
        meta_path = os.path.join(task_dir, "metadata.json")
        if not os.path.exists(meta_path):
            return
        with open(meta_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        if len(metadata) <= self._max_versions:
            return
        to_remove = metadata[:len(metadata) - self._max_versions]
        for entry in to_remove:
            v = entry["version"]
            snap = os.path.join(task_dir, f"v{v}.pptx")
            if os.path.exists(snap):
                os.remove(snap)
        metadata = metadata[len(metadata) - self._max_versions:]
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
