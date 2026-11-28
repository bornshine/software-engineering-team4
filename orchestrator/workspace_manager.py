from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import yaml

from .git_sandbox import GitSandbox
from .handoff_loader import compute_file_sha256
from .schemas import GitCommitEntry, SessionState, TaskKind, TaskRecord, TaskStatus
from .state_store import StateStore, atomic_write_text, force_rmtree
from .tech_bootstrap import get_scenario_dir


def _snapshot_tree(root: Path) -> Dict[str, str]:
    """统计工作区内除 .git 外的全部文件 SHA-256 快照。"""
    snap: Dict[str, str] = {}
    if not root.exists():
        return snap
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel == ".git" or rel.startswith(".git/"):
            continue
        snap[rel] = compute_file_sha256(p)
    return snap


def _is_path_allowed(rel_posix: str, allowed_prefixes: List[str]) -> bool:
    for prefix in allowed_prefixes:
        norm = prefix.replace("\\", "/")
        if rel_posix == norm.rstrip("/") or rel_posix.startswith(norm):
            return True
    return False


@dataclass
class AttemptWorkspace:
    attempt_dir: Path
    baseline_snapshot: Dict[str, str]
    used_worktree: bool


@dataclass
class MergeResult:
    ok: bool
    commit: Optional[GitCommitEntry] = None
    git_sync_ok: bool = True
    error_reason: str = ""


class WorkspaceManager:
    """
    §7.3 隔离尝试工作区与主工作区串行合并控制器：
    1. 每次尝试基于主工作区创建 git worktree（fallback 为完整目录快照复制）。
    2. Worker 结束后比对快照，发现越界改动立即拦截并导出 audit patch 后销毁 worktree。
    3. 验收通过后由主线程单写者合并独占目录 -> 编排器重生成 game/src/generated/ -> 构建冒烟 -> 提交。
    """

    def __init__(self, workspace_root: Path, store: StateStore) -> None:
        self.workspace_root = workspace_root.resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.store = store

    def main_workspace(self, project_id: str) -> Path:
        return self.workspace_root / project_id

    def attempts_root(self, project_id: str) -> Path:
        return self.store.project_dir(project_id) / "attempts"

    def attempt_dir(self, project_id: str, task_id: str, attempt: int) -> Path:
        return self.attempts_root(project_id) / task_id / str(attempt)

    def git_for(self, project_id: str) -> GitSandbox:
        return GitSandbox(self.main_workspace(project_id))

    def ensure_project_workspace(self, session: SessionState) -> Optional[GitCommitEntry]:
        git = self.git_for(session.project_id)
        init_commit = git.ensure_initialized(session.project_id, session.spec_version)
        if init_commit is not None:
            session.git_commits.append(init_commit)
        return init_commit

    def cleanup_all_attempts(self, project_id: str) -> int:
        """崩溃重启恢复或 Delta 排空时，销毁全部残留尝试工作区（主工作区零污染）。"""
        root = self.attempts_root(project_id)
        if not root.exists():
            return 0
        git = self.git_for(project_id)
        cleaned = 0
        for task_dir in list(root.iterdir()):
            if task_dir.is_dir():
                for att_dir in list(task_dir.iterdir()):
                    if att_dir.is_dir():
                        git.remove_worktree(att_dir)
                        cleaned += 1
        force_rmtree(root)
        return cleaned

    def create_attempt_workspace(self, project_id: str, task_id: str, attempt: int) -> AttemptWorkspace:
        main_ws = self.main_workspace(project_id)
        main_ws.mkdir(parents=True, exist_ok=True)
        att_dir = self.attempt_dir(project_id, task_id, attempt)
        git = self.git_for(project_id)

        used_wt = git.create_worktree(att_dir)
        if not used_wt:
            if att_dir.exists():
                force_rmtree(att_dir)
            shutil.copytree(
                main_ws,
                att_dir,
                ignore=shutil.ignore_patterns(".git"),
            )

        baseline = _snapshot_tree(att_dir)
        return AttemptWorkspace(attempt_dir=att_dir, baseline_snapshot=baseline, used_worktree=used_wt)

    def cleanup_attempt_workspace(self, project_id: str, attempt_ws: AttemptWorkspace) -> None:
        git = self.git_for(project_id)
        if attempt_ws.used_worktree:
            git.remove_worktree(attempt_ws.attempt_dir)
        else:
            force_rmtree(attempt_ws.attempt_dir)

    def detect_and_check_changes(
        self,
        project_id: str,
        task: TaskRecord,
        attempt: int,
        attempt_ws: AttemptWorkspace,
        *,
        allow_scenario_write: bool = False,
    ) -> Tuple[bool, List[str], List[str], Optional[str]]:
        """
        核对尝试工作区内真实发生的文件变更（新增/修改/删除），确认全部落在独占目录内。
        返回: (是否全部合规, 全部变更文件列表, 越界文件列表, 若越界则保存的 patch 路径)
        """
        after = _snapshot_tree(attempt_ws.attempt_dir)
        before = attempt_ws.baseline_snapshot
        changed: List[str] = []
        for path, sha in after.items():
            if before.get(path) != sha:
                changed.append(path)
        for path in before:
            if path not in after:
                changed.append(path)
        changed = sorted(set(changed))

        allowed = list(task.writable_paths)
        if allow_scenario_write and task.kind == TaskKind.SYS and task.req_id:
            allowed.append(get_scenario_dir(task.req_id))

        violations = [p for p in changed if not _is_path_allowed(p, allowed)]
        patch_rel: Optional[str] = None
        if violations:
            lines = [
                f"# WRITE_VIOLATION patch summary for {task.task_id} attempt={attempt}",
                f"# allowed={allowed}",
            ]
            for vp in violations:
                lines.append(f"VIOLATION: {vp}")
            patch_rel = self.store.write_patch(project_id, task.task_id, attempt, "\n".join(lines) + "\n")
            return False, changed, violations, patch_rel
        return True, changed, [], None

    def save_failed_patch(
        self, project_id: str, task_id: str, attempt: int, changed_files: List[str], note: str
    ) -> str:
        content = "\n".join([f"# FAILED_ATTEMPT {task_id} attempt={attempt}", f"# note={note}", *changed_files]) + "\n"
        return self.store.write_patch(project_id, task_id, attempt, content)

    def sync_scenarios_to_main(self, project_id: str, req_id: str, source_root: Path) -> List[str]:
        """把 QA 编写且校验通过的独立验收场景写入主工作区 game/tests/scenarios/<req_id>/（作者只读）。"""
        rel_dir = get_scenario_dir(req_id)
        src = source_root / rel_dir
        dst = self.main_workspace(project_id) / rel_dir
        if not src.exists():
            return []
        if dst.exists():
            force_rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst)
        synced = [f"{rel_dir}{p.name}" for p in sorted(dst.glob("*")) if p.is_file()]
        return synced

    def regenerate_shared_generated_files(self, session: SessionState) -> None:
        """
        §5.4 与 §5.6：主线程合并完成后，统一由编排器汇总各独占目录下的 index 文件并生成到 game/src/generated/，
        避免并发工种或并发联调节点争改公共注册文件。
        """
        main_ws = self.main_workspace(session.project_id)
        gen_dir = main_ws / "game" / "src" / "generated"
        gen_dir.mkdir(parents=True, exist_ok=True)

        narrative_lines: List[Any] = []
        art_assets: List[Any] = []
        audio_assets: List[Any] = []
        modules: List[Dict[str, Any]] = []

        def _collect_yaml_indices(base_rel: str, key: str) -> List[Any]:
            base = main_ws / base_rel
            items: List[Any] = []
            if not base.exists():
                return items
            for sub in sorted(base.iterdir()):
                if not sub.is_dir():
                    continue
                for fname in ("index.yaml", "index.json"):
                    idx_file = sub / fname
                    if idx_file.exists():
                        data = yaml.safe_load(idx_file.read_text(encoding="utf-8")) or {}
                        entries = data.get(key) if isinstance(data, dict) else data
                        if isinstance(entries, list):
                            items.extend(entries)
                        break
            return items

        narrative_lines = _collect_yaml_indices("game/data/narrative", "items")
        art_assets = _collect_yaml_indices("game/assets/art", "items")
        audio_assets = _collect_yaml_indices("game/assets/audio", "items")

        for task in sorted(session.tasks.values(), key=lambda t: t.task_id):
            if task.kind == TaskKind.INTEG and task.state == TaskStatus.SUCCEEDED and task.gdd_ref:
                mod_slug = task.gdd_ref.lower()
                modules.append(
                    {
                        "gdd_id": task.gdd_ref,
                        "task_id": task.task_id,
                        "module_dir": f"game/src/modules/{mod_slug}/",
                    }
                )

        atomic_write_text(
            gen_dir / "narrative_index.json",
            json.dumps({"items": narrative_lines}, ensure_ascii=False, indent=2) + "\n",
        )
        atomic_write_text(
            gen_dir / "art_index.json",
            json.dumps({"items": art_assets}, ensure_ascii=False, indent=2) + "\n",
        )
        atomic_write_text(
            gen_dir / "audio_index.json",
            json.dumps({"items": audio_assets}, ensure_ascii=False, indent=2) + "\n",
        )
        atomic_write_text(
            gen_dir / "modules_registry.json",
            json.dumps({"modules": modules}, ensure_ascii=False, indent=2) + "\n",
        )

    def write_contracts_to_main(self, session: SessionState) -> None:
        """把编排器确定的 tech_profile / state_events / asset_schemas 落盘至主工作区 contracts/。"""
        main_ws = self.main_workspace(session.project_id)
        cdir = main_ws / "contracts"
        cdir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            cdir / "tech_profile.yaml",
            yaml.safe_dump(session.tech_profile.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        )
        if session.state_events is not None:
            atomic_write_text(
                cdir / "state_events.json",
                json.dumps(session.state_events.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            )
        if session.asset_schemas is not None:
            atomic_write_text(
                cdir / "asset_schemas.json",
                json.dumps(session.asset_schemas.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            )

    def merge_and_commit_task(
        self,
        session: SessionState,
        task: TaskRecord,
        attempt: int,
        attempt_ws: AttemptWorkspace,
        changed_files: List[str],
        *,
        is_mock_mode: bool = True,
        simulate_merge_break: bool = False,
    ) -> MergeResult:
        """§7.3 步骤 5：主线程串行合并独占目录 -> 生成汇总文件 -> 构建冒烟 -> 提交 Git。"""
        main_ws = self.main_workspace(session.project_id)
        git = self.git_for(session.project_id)

        try:
            # 1. 把独占目录变更文件复制到主工作区
            for rel in changed_files:
                if not _is_path_allowed(rel, task.writable_paths):
                    continue
                src = attempt_ws.attempt_dir / rel
                dst = main_ws / rel
                if src.exists() and src.is_file():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                elif dst.exists():
                    dst.unlink()

            # 2. TECH-001 成功后确保权威契约写入 contracts/
            if task.kind == TaskKind.TECH:
                self.write_contracts_to_main(session)

            # 3. 主线程统一生成汇总文件（game/src/generated/）
            # 先临时设想当前任务进入 SUCCEEDED 以刷新模块注册表
            prev_state = task.state
            task.state = TaskStatus.SUCCEEDED
            self.regenerate_shared_generated_files(session)

            # 4. 构建冒烟（若配置了真实构建命令且非 mock 模式则执行）
            if simulate_merge_break:
                task.state = prev_state
                git.rollback_uncommitted()
                return MergeResult(ok=False, error_reason="MERGE_BUILD_BROKEN")

            build_cmd = session.tech_profile.runtime_harness.get("build")
            if not is_mock_mode and build_cmd and (main_ws / "package.json").exists():
                proc = subprocess.run(
                    build_cmd,
                    shell=True,
                    cwd=str(main_ws),
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if proc.returncode != 0:
                    task.state = prev_state
                    git.rollback_uncommitted()
                    return MergeResult(
                        ok=False,
                        error_reason=f"MERGE_BUILD_BROKEN: {(proc.stderr or proc.stdout)[:400]}",
                    )

            # 5. 提交主工作区 Git
            msg = f"[{session.spec_version}] {task.task_id}: {task.title} (attempt {attempt})"
            commit, sync_ok = git.commit_all(msg, task_id=task.task_id, spec_version=session.spec_version)
            if not sync_ok:
                session.git_sync_pending = True
            return MergeResult(ok=True, commit=commit, git_sync_ok=sync_ok)
        except Exception as exc:
            git.rollback_uncommitted()
            return MergeResult(ok=False, error_reason=f"MERGE_BUILD_BROKEN: {exc}")

    def archive_deprecated_task(
        self,
        session: SessionState,
        req_id: str,
        writable_paths: List[str],
        to_version: str,
    ) -> Tuple[Optional[str], Optional[GitCommitEntry]]:
        """§9.2 步骤 7：主线程将废弃需求的独占目录移入 workspace/archive/<spec_version>/ 并提交一次。"""
        main_ws = self.main_workspace(session.project_id)
        arch_root = main_ws / "archive" / to_version
        moved_any = False
        for rel_dir in writable_paths:
            src = main_ws / rel_dir.rstrip("/")
            if src.exists():
                dst = arch_root / rel_dir.rstrip("/")
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    force_rmtree(dst)
                shutil.move(str(src), str(dst))
                moved_any = True

        self.regenerate_shared_generated_files(session)
        git = self.git_for(session.project_id)
        commit, sync_ok = git.commit_all(
            f"[{to_version}] deprecate {req_id}",
            task_id=req_id,
            spec_version=to_version,
        )
        if not sync_ok:
            session.git_sync_pending = True
        return (f"archive/{to_version}" if moved_any else None), commit
