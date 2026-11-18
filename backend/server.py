from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

from .orchestrator import WorkflowOrchestrator
from .rules import WorkflowRuleError


class AppContext:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.frontend_dir = root_dir / "frontend"
        self.sandbox_dir = root_dir / ".sandbox_git"
        self.orchestrator = WorkflowOrchestrator(self.sandbox_dir)


def make_handler(ctx: AppContext):
    class RequestHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:
            # 保持控制台整洁
            return

        def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _read_json_body(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                return {}
            body = self.rfile.read(length).decode("utf-8")
            return json.loads(body) if body.strip() else {}

        def _serve_static(self, rel_path: str) -> None:
            if rel_path in ("", "/"):
                rel_path = "/index.html"
            clean_rel = rel_path.lstrip("/")
            target = (ctx.frontend_dir / clean_rel).resolve()
            if not str(target).startswith(str(ctx.frontend_dir.resolve())) or not target.is_file():
                self._send_json(HTTPStatus.NOT_FOUND, {"error_code": "ERR_NOT_FOUND", "message": "Resource not found"})
                return
            mime, _ = mimetypes.guess_type(str(target))
            data = target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{mime or 'application/octet-stream'}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/state":
                self._send_json(HTTPStatus.OK, ctx.orchestrator.get_state())
                return
            if parsed.path == "/api/health":
                self._send_json(HTTPStatus.OK, {"status": "ok", "git_available": ctx.orchestrator.git_sandbox.git_available})
                return
            self._serve_static(parsed.path)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                body = self._read_json_body()
                orch = ctx.orchestrator

                if path == "/api/presets/load":
                    res = orch.load_preset(body["case_key"])
                elif path == "/api/specs/custom":
                    res = orch.load_custom_spec(
                        raw_markdown=body.get("raw_markdown", ""),
                        title=body.get("title"),
                        genre=body.get("genre", "2D / 2.5D 定制游戏"),
                    )
                elif path == "/api/orchestrator/tick":
                    res = orch.step_tick(float(body.get("hours_per_tick", 2.0)))
                elif path == "/api/orchestrator/control":
                    action = body.get("action")
                    if action == "start":
                        res = orch.set_running(True)
                    elif action == "pause":
                        res = orch.set_running(False)
                    elif action == "rollback":
                        res = orch.rollback_to_stage(body["stage_id"])
                    else:
                        raise WorkflowRuleError("ERR_INVALID_ACTION", f"未知编排控制指令：{action}")
                elif path == "/api/tasks/verdict":
                    res = orch.submit_planner_verdict(
                        task_id=body["task_id"],
                        decision_conclusion=body.get("decision_conclusion", ""),
                        rationale=body.get("rationale", ""),
                        memory_ref_id=body.get("memory_ref_id"),
                        resolve_action=body.get("resolve_action", "APPROVE_COMPLETE"),
                    )
                elif path == "/api/tasks/reject":
                    res = orch.reject_task_qa(
                        task_id=body["task_id"],
                        reason=body.get("reason", "独立 QA 核验未通过"),
                    )
                elif path == "/api/tasks/retry":
                    res = orch.retry_failed_task(body["task_id"])
                elif path == "/api/tasks/verify":
                    res = orch.verify_task_qa(
                        task_id=body["task_id"],
                        passed=bool(body.get("passed", True)),
                        note=body.get("note", ""),
                    )
                elif path == "/api/tasks/reassign":
                    res = orch.reassign_task(
                        task_id=body["task_id"],
                        target_bot_id=body["target_bot_id"],
                    )
                elif path == "/api/tasks/delay":
                    res = orch.inject_delay(
                        task_id=body["task_id"],
                        delay_hours=float(body.get("delay_hours", 4.0)),
                    )
                elif path == "/api/tasks/validate_tags":
                    res = orch.validate_arbitrary_task_tags(body.get("tags", []))
                elif path == "/api/memory/add":
                    res = orch.add_pitfall_memory(
                        context_scenario=body.get("context_scenario", ""),
                        past_failure=body.get("past_failure", ""),
                        lesson_learned=body.get("lesson_learned", ""),
                        source_event_id=body.get("source_event_id", "MANUAL-ENTRY"),
                    )
                elif path == "/api/memory/toggle":
                    res = orch.toggle_pitfall_memory(
                        memory_id=body["memory_id"],
                        active=bool(body.get("active", True)),
                    )
                elif path == "/api/signals/inject":
                    res = orch.inject_signal(
                        raw_text=body.get("raw_text", ""),
                        source_type=body.get("source_type", "PLAYER_FEEDBACK"),
                    )
                elif path == "/api/signals/approve":
                    res = orch.approve_signal_replan(
                        signal_id=body["signal_id"],
                        decision_conclusion=body.get("decision_conclusion", ""),
                        rationale=body.get("rationale", ""),
                        memory_ref_id=body.get("memory_ref_id"),
                    )
                else:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error_code": "ERR_NOT_FOUND", "message": f"Unknown API endpoint: {path}"})
                    return

                self._send_json(HTTPStatus.OK, res)
            except WorkflowRuleError as err:
                self._send_json(HTTPStatus.BAD_REQUEST, err.to_dict())
            except (KeyError, ValueError, json.JSONDecodeError) as err:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error_code": "ERR_BAD_REQUEST", "message": str(err)})
            except Exception as err:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error_code": "ERR_INTERNAL", "message": str(err)})

    return RequestHandler


def create_server(root_dir: Path, host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    ctx = AppContext(root_dir)
    handler = make_handler(ctx)
    return ThreadingHTTPServer((host, port), handler)
