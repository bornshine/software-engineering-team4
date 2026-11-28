from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .budget_guard import BudgetGuard
from .schemas import SessionState


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_write_text(path: Path, content: str) -> None:
    """同目录临时文件 -> flush + fsync -> os.replace 原子落盘（§10.1）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def force_rmtree(path: Path) -> None:
    """兼容 Windows 只读文件（如 .git 对象）的目录清理。"""
    if not path.exists():
        return

    def _on_exc(func: Any, target: str, exc: BaseException) -> None:
        try:
            os.chmod(target, 0o700)
            func(target)
        except Exception:
            pass

    shutil.rmtree(path, onexc=_on_exc)


class StateStore:
    """§10.1 持久化与审计管理器：单文件 session_state.json + 只追加脱敏 events.jsonl。"""

    def __init__(self, state_root: Path, guard: Optional[BudgetGuard] = None) -> None:
        self.state_root = state_root.resolve()
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.guard = guard or BudgetGuard()

    def project_dir(self, project_id: str) -> Path:
        return self.state_root / project_id

    def state_file(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "session_state.json"

    def events_file(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "events.jsonl"

    def list_project_ids(self) -> List[str]:
        if not self.state_root.exists():
            return []
        ids: List[str] = []
        for entry in sorted(self.state_root.iterdir()):
            if entry.is_dir() and (entry / "session_state.json").exists():
                ids.append(entry.name)
        return ids

    def load_session(self, project_id: str) -> Optional[SessionState]:
        fpath = self.state_file(project_id)
        if not fpath.exists():
            return None
        data = json.loads(fpath.read_text(encoding="utf-8"))
        return SessionState.model_validate(data)

    def save_session(self, session: SessionState) -> None:
        payload = self.guard.redact_obj(session.model_dump(mode="json"))
        atomic_write_text(
            self.state_file(session.project_id),
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )

    def append_event(
        self,
        session: SessionState,
        event_type: str,
        *,
        task_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        session.last_event_seq += 1
        evt = {
            "seq": session.last_event_seq,
            "event_type": event_type,
            "project_id": session.project_id,
            "task_id": task_id,
            "spec_version": session.spec_version,
            "payload": self.guard.redact_obj(payload or {}),
            "occurred_at": utc_now_iso(),
        }
        epath = self.events_file(session.project_id)
        epath.parent.mkdir(parents=True, exist_ok=True)
        with open(epath, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(evt, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return evt

    def read_events(self, project_id: str, since_seq: int = 0) -> List[Dict[str, Any]]:
        epath = self.events_file(project_id)
        if not epath.exists():
            return []
        events: List[Dict[str, Any]] = []
        for line in epath.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if int(item.get("seq", 0)) > since_seq:
                events.append(item)
        return events

    def archive_handoff_copy(self, project_id: str, spec_version: str, source_dir: Path) -> Path:
        dest = self.project_dir(project_id) / "handoffs" / spec_version
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_dir, dest)
        return dest

    def write_context(self, project_id: str, task_id: str, attempt: int, ctx_dict: Dict[str, Any]) -> str:
        rel = Path("contexts") / task_id / str(attempt) / "task_context.json"
        dest = self.project_dir(project_id) / rel
        safe = self.guard.redact_obj(ctx_dict)
        atomic_write_text(dest, json.dumps(safe, ensure_ascii=False, indent=2) + "\n")
        return rel.as_posix()

    def write_report(self, project_id: str, task_id: str, attempt: int, report_dict: Dict[str, Any]) -> str:
        rel = Path("reports") / task_id / str(attempt) / "verify_report.json"
        dest = self.project_dir(project_id) / rel
        safe = self.guard.redact_obj(report_dict)
        atomic_write_text(dest, json.dumps(safe, ensure_ascii=False, indent=2) + "\n")
        return rel.as_posix()

    def write_patch(self, project_id: str, task_id: str, attempt: int, patch_text: str) -> str:
        rel = Path("patches") / task_id / f"{attempt}.patch"
        dest = self.project_dir(project_id) / rel
        atomic_write_text(dest, self.guard.redact_text(patch_text))
        return rel.as_posix()

    def write_change_request(self, project_id: str, request_id: str, yaml_text: str) -> Path:
        dest = self.project_dir(project_id) / "change_requests" / f"{request_id}.yaml"
        atomic_write_text(dest, yaml_text)
        return dest
