from __future__ import annotations

import json
import os
import pathlib
import tempfile
import threading
from typing import Optional

import models


class JsonRepository:
    def __init__(self, root_dir: Optional[pathlib.Path | str] = None, autosave: bool = True) -> None:
        self.root_dir = pathlib.Path(root_dir) if root_dir is not None else pathlib.Path.home() / ".kanban_manager"
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.root_dir / "state.json"
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self.autosave = autosave

    def load(self) -> models.AppState:
        if not self.state_file.exists():
            return models.AppState()
        with self.state_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return models.AppState.from_dict(data)

    def save(self, state: models.AppState) -> None:
        data = state.to_dict()
        tmp_fd, tmp_path = tempfile.mkstemp(dir=self.root_dir, prefix="state_", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_file:
                json.dump(data, tmp_file, ensure_ascii=False, indent=2)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_path, self.state_file)
        finally:
            # If replace failed, ensure tmp is removed
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    def save_debounced(self, state: models.AppState, delay_sec: float = 0.5) -> None:
        # For deterministic tests and reliability, if autosave is False, save immediately.
        if not self.autosave or delay_sec <= 0:
            with self._lock:
                self.save(state)
            return

        def _save():
            with self._lock:
                self.save(state)

        with self._lock:
            if self._timer is not None:
                try:
                    self._timer.cancel()
                except Exception:
                    pass
                self._timer = None
            self._timer = threading.Timer(delay_sec, _save)
            self._timer.daemon = True
            self._timer.start()
