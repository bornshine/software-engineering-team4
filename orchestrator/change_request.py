from __future__ import annotations

from datetime import datetime, timezone
from typing import List
import yaml

from .schemas import ChangeRequest, SessionState, TaskStatus
from .state_store import StateStore


def build_and_export_change_request(
    session: SessionState,
    store: StateStore,
    *,
    trigger_source: str,
    impacted_req_ids: List[str],
    problem_statement: str,
    requested_delta: str,
) -> ChangeRequest:
    """
    §9.1：按契约第四章 Schema 生成并导出 change_request.yaml 供第一层 Delta RFC 消费；
    同时将关联未完成任务置为 BLOCKED，等待新版本交接包到达。
    """
    date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")
    seq_no = len(session.change_requests) + 1
    request_id = f"CR-{date_tag}-{seq_no:02d}"

    cr = ChangeRequest(
        request_id=request_id,
        project_id=session.project_id,
        base_spec_version=session.spec_version,
        trigger_source=trigger_source,  # type: ignore[arg-type]
        impacted_req_ids=list(impacted_req_ids),
        problem_statement=problem_statement.strip(),
        requested_delta=requested_delta.strip(),
    )
    yaml_text = yaml.safe_dump(cr.model_dump(mode="json"), allow_unicode=True, sort_keys=False)
    out_path = store.write_change_request(session.project_id, request_id, yaml_text)

    session.change_requests.append(cr)
    for rid in impacted_req_ids:
        task = session.tasks.get(rid)
        if task and task.state != TaskStatus.SUCCEEDED:
            task.state = TaskStatus.BLOCKED
            task.decision_kind = None

    store.append_event(
        session,
        "CHANGE_REQUEST_EXPORTED",
        payload={
            "request_id": request_id,
            "trigger_source": trigger_source,
            "impacted_req_ids": impacted_req_ids,
            "path": out_path.as_posix(),
        },
    )
    return cr
