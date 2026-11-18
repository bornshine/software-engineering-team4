from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional
from .models import GitCommitRecord
from .planner_memory import utc_now_str


class GitSandbox:
    """
    第 9.3 节：沙箱 Git 仓库管理器。
    在本地隔离目录 .sandbox_git 中真实执行 git init / checkout -b / commit / log --graph，
    同时维护结构化 GitCommitRecord 供前端可视化演化树渲染。
    """

    def __init__(self, sandbox_dir: Path):
        self.sandbox_dir = sandbox_dir
        self.commits: List[GitCommitRecord] = []
        self.current_branch = "main"
        self.head_hash: Optional[str] = None
        self.git_available = self._check_git()

    def _check_git(self) -> bool:
        try:
            res = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=5)
            return res.returncode == 0
        except Exception:
            return False

    def _run_git(self, args: List[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            cwd=str(self.sandbox_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )

    def init_repo(self, spec_id: str, spec_title: str, raw_markdown: str, sha256: str) -> GitCommitRecord:
        if self.sandbox_dir.exists():
            shutil.rmtree(self.sandbox_dir, ignore_errors=True)
        self.sandbox_dir.mkdir(parents=True, exist_ok=True)
        self.commits = []
        self.current_branch = "main"
        self.head_hash = None

        spec_file = self.sandbox_dir / "DESIGN_SPEC.md"
        spec_file.write_text(raw_markdown, encoding="utf-8")

        meta_file = self.sandbox_dir / "spec_meta.json"
        meta_file.write_text(
            json.dumps({"spec_id": spec_id, "title": spec_title, "sha256": sha256}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if self.git_available:
            self._run_git(["init", "-b", "main"])
            self._run_git(["config", "user.name", "RJGC-Orchestrator"])
            self._run_git(["config", "user.email", "orchestrator@rjgc-game.local"])
            self._run_git(["config", "core.quotepath", "false"])
            self._run_git(["add", "."])
            self._run_git(["commit", "-m", f"chore(spec): init {spec_id} ({spec_title}) [sha:{sha256[:8]}]"])
            rev = self._run_git(["rev-parse", "--short", "HEAD"])
            commit_hash = rev.stdout.strip() or sha256[:7]
        else:
            commit_hash = sha256[:7]

        rec = GitCommitRecord(
            commit_hash=commit_hash,
            parent_hashes=[],
            branch="main",
            message=f"chore(spec): init {spec_id} ({spec_title}) [sha:{sha256[:8]}]",
            timestamp=utc_now_str(),
            event_type="SPEC_INIT",
            related_ids=[spec_id],
        )
        self.commits.append(rec)
        self.head_hash = commit_hash
        return rec

    def commit_event(
        self,
        branch: str,
        message: str,
        event_type: str,
        related_ids: List[str],
        artifact_rel_path: Optional[str] = None,
        artifact_content: Optional[str] = None,
        merge_to_main: bool = True,
    ) -> GitCommitRecord:
        parent_hashes = [self.head_hash] if self.head_hash else []

        if artifact_rel_path and artifact_content is not None:
            target = self.sandbox_dir / artifact_rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(artifact_content, encoding="utf-8")

        if self.git_available:
            if branch != "main":
                # 切到 feature 分支提交后再合并回 main，形成真实分支演化树
                chk = self._run_git(["checkout", "-B", branch])
                if chk.returncode != 0:
                    self._run_git(["checkout", "main"])
                    self._run_git(["checkout", "-B", branch])
            else:
                self._run_git(["checkout", "main"])

            self._run_git(["add", "."])
            c_res = self._run_git(["commit", "--allow-empty", "-m", message])
            if c_res.returncode != 0:
                self._run_git(["commit", "--allow-empty", "-m", message])
            rev = self._run_git(["rev-parse", "--short", "HEAD"])
            commit_hash = rev.stdout.strip() or hashlib.sha1(f"{message}{len(self.commits)}".encode()).hexdigest()[:7]

            if branch != "main" and merge_to_main:
                self._run_git(["checkout", "main"])
                self._run_git(["merge", "--no-ff", branch, "-m", f"merge({branch}): {message}"])
                rev_m = self._run_git(["rev-parse", "--short", "HEAD"])
                if rev_m.returncode == 0 and rev_m.stdout.strip():
                    # 记录 feature commit 与 main merge 节点
                    feat_rec = GitCommitRecord(
                        commit_hash=commit_hash,
                        parent_hashes=parent_hashes,
                        branch=branch,
                        message=message,
                        timestamp=utc_now_str(),
                        event_type=event_type,
                        related_ids=related_ids,
                    )
                    self.commits.append(feat_rec)
                    merge_hash = rev_m.stdout.strip()
                    merge_rec = GitCommitRecord(
                        commit_hash=merge_hash,
                        parent_hashes=[self.head_hash, commit_hash] if self.head_hash else [commit_hash],
                        branch="main",
                        message=f"merge({branch}): {message}",
                        timestamp=utc_now_str(),
                        event_type=event_type,
                        related_ids=related_ids,
                    )
                    self.commits.append(merge_rec)
                    self.head_hash = merge_hash
                    return feat_rec
        else:
            commit_hash = hashlib.sha1(f"{branch}:{message}:{len(self.commits)}".encode()).hexdigest()[:7]

        rec = GitCommitRecord(
            commit_hash=commit_hash,
            parent_hashes=parent_hashes,
            branch=branch,
            message=message,
            timestamp=utc_now_str(),
            event_type=event_type,
            related_ids=related_ids,
        )
        self.commits.append(rec)
        self.head_hash = commit_hash
        return rec

    def get_graph_text(self, limit: int = 40) -> str:
        if self.git_available and (self.sandbox_dir / ".git").exists():
            res = self._run_git(["log", "--all", "--graph", "--oneline", "--decorate", f"-n{limit}"])
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        lines = []
        for idx, c in enumerate(reversed(self.commits[-limit:])):
            prefix = "* " if c.branch == "main" else "| * "
            lines.append(f"{prefix}{c.commit_hash} ({c.branch}) {c.message}")
        return "\n".join(lines)

    def get_branches(self) -> List[str]:
        if self.git_available and (self.sandbox_dir / ".git").exists():
            res = self._run_git(["branch", "--format=%(refname:short)"])
            if res.returncode == 0 and res.stdout.strip():
                return [b.strip() for b in res.stdout.splitlines() if b.strip()]
        return sorted(list({c.branch for c in self.commits}))
