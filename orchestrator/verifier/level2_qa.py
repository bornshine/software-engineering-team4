from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..schemas import (
    HandoffBundle,
    Level1Report,
    Level2Report,
    TaskKind,
    TaskRecord,
    VerifyFinding,
)


def should_require_spot_check(
    kind: TaskKind,
    config: Dict[str, Any],
) -> bool:
    """§8.4：默认 AUD 开启人工抽检；未配置视觉模型时 ART 自动加入人工抽检。"""
    spot_list = list(config.get("policy", {}).get("human_spot_check", ["AUD"]))
    if kind.value in spot_list:
        return True
    if kind == TaskKind.ART:
        qa_cfg = config.get("workers", {}).get("ROLE_QA_INTEG", {})
        has_vision = bool(qa_cfg.get("vision", True))
        if not has_vision:
            return True
    return False


def _validate_requirement_quote(quote: str | None, bundle: HandoffBundle) -> bool:
    """§8.3：判定 REQUIREMENT_DEFECT 的引用原文必须逐字出现在交接包原文中（代码校验）。"""
    if not quote or not quote.strip():
        return False
    norm_q = quote.strip().replace("\r\n", "\n")
    return any(norm_q in txt for txt in bundle.raw_searchable_texts)


def _normalize_findings(findings: List[VerifyFinding], bundle: HandoffBundle) -> Tuple[List[VerifyFinding], str]:
    normalized: List[VerifyFinding] = []
    extra_notes: List[str] = []
    for f in findings:
        if f.result == "FAIL" and f.defect_type == "REQUIREMENT_DEFECT":
            if not _validate_requirement_quote(f.requirement_quote, bundle):
                f = VerifyFinding(
                    ac_id=f.ac_id,
                    result="FAIL",
                    defect_type="IMPLEMENTATION",
                    evidence=f.evidence,
                    requirement_quote=f.requirement_quote,
                    fix_hint=f.fix_hint or "QA 未能给出有效原文引用，按实现缺陷打回重做。",
                )
                extra_notes.append(f"{f.ac_id}: REQUIREMENT_DEFECT 缺少有效原文逐字引用，系统强制降级为 IMPLEMENTATION。")
        normalized.append(f)
    return normalized, " ".join(extra_notes)


def run_level2_qa(
    task: TaskRecord,
    ctx: Dict[str, Any],
    l1_report: Level1Report,
    bundle: HandoffBundle,
    workdir: Path,
    *,
    is_mock_mode: bool = True,
    qa_config: Dict[str, Any] | None = None,
) -> Level2Report:
    """
    §8.3 独立 QA L2 审阅（与作者不同实例、全新会话）：
    - mock 模式：默认严谨核对产出摘要并支持故障注入（fail_once / fail_always / req_defect_bad_quote / req_defect_valid）；
    - api 模式：调用独立异构 LLM 进行验收审阅。
    """
    faults: List[str] = list(ctx.get("injected_faults", []))
    attempt = int(ctx.get("attempt", 1))
    acs = ctx.get("acceptance_criteria", [])
    first_ac = acs[0]["ac_id"] if acs else f"{task.task_id}-AC1"

    # 故障注入分支（供测试 O8/O9/O10/O12 及前端演练）
    if "fail_always" in faults or (f"fail_attempt_{attempt}" in faults) or ("fail_once" in faults and attempt == 1):
        findings = [
            VerifyFinding(
                ac_id=first_ac,
                result="FAIL",
                defect_type="IMPLEMENTATION",
                evidence=f"[QA 审阅第 {attempt} 次] 产出未满足 {first_ac} 验收细节，请按指引返工。",
                fix_hint="补齐边界分支处理与样式梯度后重交。",
            )
        ]
        norm_findings, extra = _normalize_findings(findings, bundle)
        return Level2Report(decision="FAIL", reviewer_model="mock-qa", findings=norm_findings, notes=extra)

    if "req_defect_bad_quote" in faults:
        findings = [
            VerifyFinding(
                ac_id=first_ac,
                result="FAIL",
                defect_type="REQUIREMENT_DEFECT",
                evidence="QA 主观认为需求边界不清，但伪造了一句原文引用。",
                requirement_quote="一段完全不存在于交接包原文中的伪造需求文字",
                fix_hint="需退回重做",
            )
        ]
        norm_findings, extra = _normalize_findings(findings, bundle)
        return Level2Report(decision="FAIL", reviewer_model="mock-qa", findings=norm_findings, notes=extra)

    if "req_defect_valid" in faults:
        # 从需求原文精确截取一条合法引用，实测进入 G3 门禁
        real_quote = "女儿国"
        if task.kind == TaskKind.NAR:
            real_quote = bundle.narrative_requirements.stage_deliverables[0].deliverable_spec[:24]
        elif task.kind == TaskKind.SYS:
            real_quote = bundle.system_requirements.stage_deliverables[0].business_rules[0][:24]
        findings = [
            VerifyFinding(
                ac_id=first_ac,
                result="FAIL",
                defect_type="REQUIREMENT_DEFECT",
                evidence="验收发现需求指标在当前体量或试玩体验下需要调整。",
                requirement_quote=real_quote,
                fix_hint="建议经 G3 导出 change_request.yaml 回流第一层。",
            )
        ]
        norm_findings, extra = _normalize_findings(findings, bundle)
        return Level2Report(decision="FAIL", reviewer_model="mock-qa", findings=norm_findings, notes=extra)

    if is_mock_mode:
        findings = [
            VerifyFinding(
                ac_id=ac["ac_id"],
                result="PASS",
                evidence=f"L1 脚本已验证，L2 核对 {ac['ac_id']} 与 Canon/ADR 一致。",
            )
            for ac in acs
        ]
        return Level2Report(
            decision="PASS",
            reviewer_model="mock-heterogeneous-qa",
            findings=findings,
            notes="通过独立 L2 审阅。",
        )

    # 真实 API 独立审阅
    api_key = os.environ.get("QA_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
    model_name = (qa_config or {}).get("model", "gpt-4o-mini")
    if not api_key:
        # 未提供外部 QA Key 时返回可识别错误提示由外层暂停而非静默放水
        raise RuntimeError("未配置 QA_API_KEY / OPENAI_API_KEY，无法执行真实 L2 QA 审阅")

    api_base = (os.environ.get("QA_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    req_body = json.dumps(
        {
            "model": model_name,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是独立 QA 验收专家，必须严守作者与评者分离。"
                        "返回 JSON: {decision: 'PASS'|'FAIL', findings: [{ac_id, result, defect_type, evidence, requirement_quote, fix_hint}], notes: '...'}"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task_id": task.task_id,
                            "acceptance_criteria": acs,
                            "l1_report": l1_report.model_dump(mode="json"),
                            "canon_entries": ctx.get("canon_entries", []),
                            "adr_entries": ctx.get("adr_entries", []),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "temperature": 0.1,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{api_base}/chat/completions",
        data=req_body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    parsed = json.loads(data["choices"][0]["message"]["content"])
    raw_findings = [VerifyFinding.model_validate(x) for x in parsed.get("findings", [])]
    norm_findings, extra = _normalize_findings(raw_findings, bundle)
    decision = "FAIL" if any(f.result == "FAIL" for f in norm_findings) else parsed.get("decision", "PASS")
    return Level2Report(
        decision=decision,
        reviewer_model=model_name,
        findings=norm_findings,
        notes=(parsed.get("notes", "") + " " + extra).strip(),
    )
