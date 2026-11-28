from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from pydantic import ValidationError

from .schemas import (
    AdrRecord,
    ArtRequirements,
    AudioRequirements,
    AuxiliaryFileRecord,
    CanonRegistry,
    DiffSummary,
    GddIndex,
    HandoffBundle,
    Manifest,
    ManifestFileEntry,
    NarrativeRequirements,
    OrchestratorError,
    SystemRequirements,
)

TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".txt"}


def compute_file_sha256(path: Path) -> str:
    """按契约计算文件 SHA-256；文本文件归一化为 LF、UTF-8 无 BOM 保证跨平台一致。"""
    raw = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES:
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        raw = text.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def compute_canonical_sha256(entries: List[ManifestFileEntry]) -> str:
    """按 §4.2 规则对规范化排序的受管文件哈希再次计算包级摘要。"""
    lines = sorted(f"{e.path.replace(chr(92), '/')}:{e.sha256}" for e in entries)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def stable_json_sha256(obj: Any) -> str:
    """计算结构化对象的确定性规范化 SHA-256。"""
    payload = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_yaml_file(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
        return yaml.safe_load(text)
    except Exception as exc:
        raise OrchestratorError(
            "ERR_SCHEMA_INVALID",
            f"YAML 解析失败: {path.as_posix()} ({exc})",
            {"path": path.as_posix()},
        ) from exc


def _load_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise OrchestratorError(
            "ERR_SCHEMA_INVALID",
            f"JSON 解析失败: {path.as_posix()} ({exc})",
            {"path": path.as_posix()},
        ) from exc


def _parse_model(model_cls: Any, data: Any, rel_path: str) -> Any:
    try:
        return model_cls.model_validate(data)
    except ValidationError as exc:
        raise OrchestratorError(
            "ERR_SCHEMA_INVALID",
            f"文件 {rel_path} 未通过 Schema 校验: {exc.errors()[0]['msg']}",
            {"path": rel_path, "errors": exc.errors()},
        ) from exc


def load_handoff_bundle(handoff_dir: Path, auxiliary_mode: str = "compat") -> HandoffBundle:
    """读取并解析第一层冻结交接包，物理隔离 ideas_backlog.md。"""
    root = handoff_dir.resolve()
    if not root.exists() or not root.is_dir():
        raise OrchestratorError(
            "ERR_HANDOFF_NOT_FOUND",
            f"交接包目录不存在: {handoff_dir}",
            {"path": str(handoff_dir)},
        )

    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise OrchestratorError(
            "ERR_SCHEMA_INVALID",
            "缺少交接包总入口 manifest.json",
            {"path": manifest_path.as_posix()},
        )
    manifest = _parse_model(Manifest, _load_json_file(manifest_path), "manifest.json")

    listed_paths = {entry.path.replace("\\", "/") for entry in manifest.files}
    req_paths = {
        "master_gdd": "MASTER_GDD.md",
        "gdd_index": "gdd_index.yaml",
        "system": "requirements/system_requirements.yaml",
        "narrative": "requirements/narrative_requirements.yaml",
        "art": "requirements/art_requirements.yaml",
        "audio": "requirements/audio_requirements.yaml",
        "canon": "memory/canon_registry.yaml",
    }
    for rel in req_paths.values():
        if not (root / rel).exists():
            raise OrchestratorError(
                "ERR_SCHEMA_INVALID",
                f"交接包缺少必需文件: {rel}",
                {"path": rel},
            )

    master_gdd_md = (root / req_paths["master_gdd"]).read_text(encoding="utf-8")
    gdd_index = _parse_model(GddIndex, _load_yaml_file(root / req_paths["gdd_index"]), req_paths["gdd_index"])
    sys_req = _parse_model(SystemRequirements, _load_yaml_file(root / req_paths["system"]), req_paths["system"])
    nar_req = _parse_model(NarrativeRequirements, _load_yaml_file(root / req_paths["narrative"]), req_paths["narrative"])
    art_req = _parse_model(ArtRequirements, _load_yaml_file(root / req_paths["art"]), req_paths["art"])
    aud_req = _parse_model(AudioRequirements, _load_yaml_file(root / req_paths["audio"]), req_paths["audio"])
    canon = _parse_model(CanonRegistry, _load_yaml_file(root / req_paths["canon"]), req_paths["canon"])

    diff_summary: Optional[DiffSummary] = None
    if manifest.diff_summary_ref:
        diff_rel = manifest.diff_summary_ref.replace("\\", "/")
        diff_file = root / diff_rel
        if not diff_file.exists():
            raise OrchestratorError(
                "ERR_SCHEMA_INVALID",
                f"manifest 声明了 diff_summary_ref='{diff_rel}'，但文件不存在。",
                {"path": diff_rel},
            )
        diff_summary = _parse_model(DiffSummary, _load_yaml_file(diff_file), diff_rel)

    # 扫描辅助文件：ADR 与参考图（兼容 A-10）
    auxiliary_records: List[AuxiliaryFileRecord] = []
    adr_records: List[AdrRecord] = []
    adr_dir = root / "memory" / "adr"
    if adr_dir.exists():
        for adr_file in sorted(adr_dir.glob("*.yaml")):
            rel = adr_file.relative_to(root).as_posix()
            in_manifest = rel in listed_paths
            file_hash = compute_file_sha256(adr_file)
            auxiliary_records.append(
                AuxiliaryFileRecord(path=rel, sha256=file_hash, listed_in_manifest=in_manifest, kind="adr")
            )
            if in_manifest or auxiliary_mode == "compat":
                adr_records.append(_parse_model(AdrRecord, _load_yaml_file(adr_file), rel))

    reference_images: List[str] = []
    ref_dir = root / "references"
    if ref_dir.exists():
        for ref_file in sorted(ref_dir.iterdir()):
            if ref_file.is_file():
                rel = ref_file.relative_to(root).as_posix()
                in_manifest = rel in listed_paths
                file_hash = compute_file_sha256(ref_file)
                auxiliary_records.append(
                    AuxiliaryFileRecord(path=rel, sha256=file_hash, listed_in_manifest=in_manifest, kind="reference")
                )
                if in_manifest or auxiliary_mode == "compat":
                    reference_images.append(rel)

    # 物理隔离 memory/ideas_backlog.md：只记审计哈希，不读取正文进入业务模型
    backlog_file = root / "memory" / "ideas_backlog.md"
    backlog_sha: Optional[str] = compute_file_sha256(backlog_file) if backlog_file.exists() else None

    gc_hashes = {
        "system": stable_json_sha256(sys_req.global_constraints),
        "narrative": stable_json_sha256(nar_req.global_constraints),
        "art": stable_json_sha256(art_req.global_constraints),
        "audio": stable_json_sha256(aud_req.global_constraints),
    }

    # 用于 L2 REQUIREMENT_DEFECT 逐字引用校验的原文字料池（仅来自正规需求/GDD/Canon/ADR，不含 backlog）
    searchable: List[str] = [master_gdd_md]
    for fpath in [
        req_paths["gdd_index"],
        req_paths["system"],
        req_paths["narrative"],
        req_paths["art"],
        req_paths["audio"],
        req_paths["canon"],
    ]:
        searchable.append((root / fpath).read_text(encoding="utf-8").replace("\r\n", "\n"))
    if adr_dir.exists():
        for adr_file in sorted(adr_dir.glob("*.yaml")):
            searchable.append(adr_file.read_text(encoding="utf-8").replace("\r\n", "\n"))

    return HandoffBundle(
        source_dir=root.as_posix(),
        manifest=manifest,
        master_gdd_markdown=master_gdd_md,
        gdd_index=gdd_index,
        system_requirements=sys_req,
        narrative_requirements=nar_req,
        art_requirements=art_req,
        audio_requirements=aud_req,
        canon_registry=canon,
        adr_records=adr_records,
        reference_images=reference_images,
        diff_summary=diff_summary,
        auxiliary_files=auxiliary_records,
        backlog_audit_sha256=backlog_sha,
        global_constraints_hashes=gc_hashes,
        raw_searchable_texts=searchable,
    )
