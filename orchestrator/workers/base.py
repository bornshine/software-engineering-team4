from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Protocol

from ..schemas import ArtifactManifest


@dataclass
class WorkerResult:
    ok: bool
    manifest: Optional[ArtifactManifest] = None
    error_message: str = ""
    api_calls: int = 0
    cost: float = 0.0
    runtime_sec: float = 0.0
    timed_out: bool = False


class WorkerAdapter(Protocol):
    """§7.4 热插拔生产 Worker 协议：可在 mock / api / cli 之间无缝切换。"""

    role: str
    mode: Literal["mock", "api", "cli"]

    def run(self, ctx: Dict[str, Any], workdir: Path, timeout_sec: int) -> WorkerResult:
        """在给定尝试工作区 workdir 中生产产物，仅允许写入 ctx['writable_paths']。"""
        ...
