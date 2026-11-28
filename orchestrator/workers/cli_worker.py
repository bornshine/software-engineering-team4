from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..schemas import ArtifactManifest
from .base import WorkerResult


def _build_restricted_env(allowlist: List[str]) -> Dict[str, str]:
    """§7.5 白名单注入 CLI 运行环境变量，不透传宿主根目录 .env 等无关凭据。"""
    base_keys = ["PATH", "SystemRoot", "COMSPEC", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG"]
    env: Dict[str, str] = {}
    for k in [*base_keys, *allowlist]:
        if k in os.environ:
            env[k] = os.environ[k]
    return env


class CliWorker:
    """
    §7.4 原厂 Agent CLI Worker（codex-cli / claude-cli / gemini-cli）：
    - 在隔离尝试工作区 workdir 中以独立子进程启动；
    - 强制白名单环境变量 + 超时整棵进程树终止。
    """

    mode = "cli"

    def __init__(
        self,
        role: str,
        *,
        runtime: str = "codex-cli",
        env_allowlist: Optional[List[str]] = None,
    ) -> None:
        self.role = role
        self.runtime = runtime
        self.env_allowlist = env_allowlist or ["OPENAI_API_KEY"]

    def _resolve_command(self, prompt_file: Path) -> List[str]:
        exe_map = {
            "codex-cli": ["codex", "exec", "-"],
            "claude-cli": ["claude", "-p"],
            "gemini-cli": ["gemini", "-p"],
        }
        return exe_map.get(self.runtime, [self.runtime])

    def run(self, ctx: Dict[str, Any], workdir: Path, timeout_sec: int) -> WorkerResult:
        started = time.perf_counter()
        prompt_path = workdir / ".task_prompt.json"
        prompt_path.write_text(json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")

        cmd = self._resolve_command(prompt_path)
        if shutil.which(cmd[0]) is None:
            if prompt_path.exists():
                prompt_path.unlink()
            return WorkerResult(
                ok=False,
                error_message=f"未安装原厂 CLI '{cmd[0]}'（{self.runtime}），请安装或切换 --mock / api 模式。",
                runtime_sec=round(time.perf_counter() - started, 4),
            )

        env = _build_restricted_env(self.env_allowlist)
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(workdir),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            prompt_text = (
                f"请严格按 .task_prompt.json 完成任务 {ctx['task_id']}，仅修改允许目录 {ctx['writable_paths']}。\n"
            )
            try:
                stdout, stderr = proc.communicate(input=prompt_text, timeout=timeout_sec)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
                else:
                    proc.kill()
                proc.communicate()
                return WorkerResult(
                    ok=False,
                    timed_out=True,
                    error_message=f"CLI 进程超时 ({timeout_sec}s) 已强杀进程树",
                    api_calls=1,
                    cost=0.1,
                    runtime_sec=round(time.perf_counter() - started, 4),
                )
            finally:
                if prompt_path.exists():
                    prompt_path.unlink()

            if proc.returncode != 0:
                return WorkerResult(
                    ok=False,
                    error_message=f"CLI 执行失败 (exit={proc.returncode}): {stderr[:400]}",
                    api_calls=1,
                    cost=0.1,
                    runtime_sec=round(time.perf_counter() - started, 4),
                )

            return WorkerResult(
                ok=True,
                manifest=ArtifactManifest(
                    task_id=ctx["task_id"],
                    attempt=int(ctx.get("attempt", 1)),
                    files=[],
                    summary=f"CLI ({self.runtime}) 完成任务: {stdout.strip()[:200]}",
                    api_calls=1,
                    cost=0.1,
                ),
                api_calls=1,
                cost=0.1,
                runtime_sec=round(time.perf_counter() - started, 4),
            )
        except Exception as exc:
            if prompt_path.exists():
                prompt_path.unlink()
            return WorkerResult(
                ok=False,
                error_message=f"CLI 调用异常: {exc}",
                runtime_sec=round(time.perf_counter() - started, 4),
            )
