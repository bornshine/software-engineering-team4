from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from .schemas import GitCommitEntry
from .state_store import force_rmtree, utc_now_iso


class GitSandbox:
    """
    §10.4 沙箱 Git 管理器（workspace/<project_id>/ 独立仓库，与本工具仓库完全物理隔离）。
    支持隔离 attempt worktree 创建与清理、单任务合并提交、废弃归档提交与版本封版标签。
    """

    def __init__(self, repo_dir: Path) -> None:
        self.repo_dir = repo_dir.resolve()
        self.git_available = self._check_git()

    def _check_git(self) -> bool:
        try:
            res = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=5)
            return res.returncode == 0
        except Exception:
            return False

    def _run_git(self, args: List[str], cwd: Optional[Path] = None) -> Tuple[bool, str]:
        if not self.git_available:
            return False, "git unavailable"
        target_cwd = cwd or self.repo_dir
        try:
            res = subprocess.run(
                ["git", *args],
                cwd=str(target_cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            output = (res.stdout or "") + (res.stderr or "")
            return res.returncode == 0, output.strip()
        except Exception as exc:
            return False, str(exc)

    def ensure_initialized(self, project_id: str, spec_version: str) -> Optional[GitCommitEntry]:
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        git_dir = self.repo_dir / ".git"
        if git_dir.exists():
            return None

        readme = self.repo_dir / "README_WORKSPACE.md"
        readme.write_text(
            f"# {project_id} Workspace\n\nInitialized for handoff `{spec_version}`.\n",
            encoding="utf-8",
        )
        if not self.git_available:
            return GitCommitEntry(
                commit_hash=hashlib.sha256(f"{project_id}:{spec_version}:init".encode()).hexdigest()[:7],
                branch="main",
                message=f"[{spec_version}] init workspace",
                spec_version=spec_version,
                timestamp=utc_now_iso(),
            )

        ok, _ = self._run_git(["init", "-b", "main"])
        if not ok:
            self._run_git(["init"])
            self._run_git(["checkout", "-b", "main"])
        self._run_git(["config", "user.name", "RJGC-Orchestrator"])
        self._run_git(["config", "user.email", "orchestrator@rjgc-game.local"])
        self._run_git(["config", "core.quotepath", "false"])
        self._run_git(["add", "."])
        self._run_git(["commit", "-m", f"[{spec_version}] init workspace for {project_id}"])
        ok, rev = self._run_git(["rev-parse", "--short", "HEAD"])
        commit_hash = rev.strip() if ok and rev.strip() else "init000"
        return GitCommitEntry(
            commit_hash=commit_hash,
            branch="main",
            message=f"[{spec_version}] init workspace for {project_id}",
            spec_version=spec_version,
            timestamp=utc_now_iso(),
        )

    def create_worktree(self, worktree_dir: Path) -> bool:
        """创建隔离尝试 worktree；失败则返回 False 由上层回退到目录拷贝隔离。"""
        if worktree_dir.exists():
            self.remove_worktree(worktree_dir)
        worktree_dir.parent.mkdir(parents=True, exist_ok=True)
        if not self.git_available or not (self.repo_dir / ".git").exists():
            return False
        ok, _ = self._run_git(["worktree", "add", "--detach", str(worktree_dir), "HEAD"])
        return ok

    def remove_worktree(self, worktree_dir: Path) -> None:
        if self.git_available and (self.repo_dir / ".git").exists():
            self._run_git(["worktree", "remove", "--force", str(worktree_dir)])
            self._run_git(["worktree", "prune"])
        if worktree_dir.exists():
            force_rmtree(worktree_dir)

    def commit_all(
        self,
        message: str,
        *,
        task_id: Optional[str] = None,
        spec_version: Optional[str] = None,
    ) -> Tuple[Optional[GitCommitEntry], bool]:
        """提交主工作区当前变更，返回 (GitCommitEntry, git_sync_ok)。"""
        if not self.git_available or not (self.repo_dir / ".git").exists():
            fallback_hash = hashlib.sha256(f"{message}:{utc_now_iso()}".encode()).hexdigest()[:7]
            return (
                GitCommitEntry(
                    commit_hash=fallback_hash,
                    branch="main",
                    message=message,
                    task_id=task_id,
                    spec_version=spec_version,
                    timestamp=utc_now_iso(),
                ),
                False,
            )

        self._run_git(["add", "-A"])
        ok_diff, _ = self._run_git(["diff", "--cached", "--quiet"])
        if ok_diff:
            # 无变更时不强行空提交，复用当前 HEAD 哈希
            ok_rev, rev = self._run_git(["rev-parse", "--short", "HEAD"])
            return (
                GitCommitEntry(
                    commit_hash=rev.strip() if ok_rev else "nochange",
                    branch="main",
                    message=message,
                    task_id=task_id,
                    spec_version=spec_version,
                    timestamp=utc_now_iso(),
                ),
                True,
            )

        ok_c, _ = self._run_git(["commit", "-m", message])
        if not ok_c:
            return None, False
        ok_rev, rev = self._run_git(["rev-parse", "--short", "HEAD"])
        return (
            GitCommitEntry(
                commit_hash=rev.strip() if ok_rev else "unknown",
                branch="main",
                message=message,
                task_id=task_id,
                spec_version=spec_version,
                timestamp=utc_now_iso(),
            ),
            True,
        )

    def rollback_uncommitted(self) -> None:
        """构建冒烟失败时清理未提交的合并脏文件。"""
        if self.git_available and (self.repo_dir / ".git").exists():
            self._run_git(["reset", "--hard", "HEAD"])
            self._run_git(["clean", "-fd"])

    def tag_release(self, spec_version: str) -> Tuple[str, bool]:
        tag_name = f"spec/{spec_version}"
        if not self.git_available or not (self.repo_dir / ".git").exists():
            return tag_name, False
        ok, _ = self._run_git(["tag", "-f", tag_name])
        return tag_name, ok
