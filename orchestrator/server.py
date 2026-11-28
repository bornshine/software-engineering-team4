from __future__ import annotations

import json
import mimetypes
import queue
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from .engine import OrchestratorEngine
from .schemas import OrchestratorError

STATIC_MAP = {
    "/": "index.html",
    "/index.html": "index.html",
    "/styles.css": "styles.css",
    "/app.js": "app.js",
}


def discover_fixtures(base_dir: Path) -> List[Dict[str, str]]:
    fix_root = base_dir / "fixtures" / "handoff"
    out: List[Dict[str, str]] = []
    if not fix_root.exists():
        return out
    for proj_dir in sorted(fix_root.iterdir()):
        if not proj_dir.is_dir():
            continue
        for ver_dir in sorted(proj_dir.iterdir()):
            if ver_dir.is_dir() and (ver_dir / "manifest.json").exists():
                out.append(
                    {
                        "label": f"{proj_dir.name} ({ver_dir.name})",
                        "project_id": proj_dir.name,
                        "spec_version": ver_dir.name,
                        "path": ver_dir.relative_to(base_dir).as_posix(),
                    }
                )
    return out


class OrchestratorHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: Tuple[str, int], engine: OrchestratorEngine, frontend_dir: Path) -> None:
        self.engine = engine
        self.frontend_dir = frontend_dir.resolve()
        super().__init__(server_address, OrchestratorRequestHandler)


class OrchestratorRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, code: int, data: Any) -> None:
        body = (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, code: int, err_code: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        self._send_json(code, {"error_code": err_code, "message": message, "details": details or {}})

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        if not raw.strip():
            return {}
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else {}
        except Exception as exc:
            raise OrchestratorError("ERR_SCHEMA_INVALID", f"请求体 JSON 解析失败: {exc}") from exc

    def _handle_static(self, path: str) -> bool:
        if path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return True
        fname = STATIC_MAP.get(path)
        if not fname:
            return False
        fpath = self.server.frontend_dir / fname  # type: ignore[attr-defined]
        if not fpath.exists():
            self._send_error_json(404, "ERR_NOT_FOUND", f"静态资源不存在: {fname}")
            return True
        data = fpath.read_bytes()
        ctype, _ = mimetypes.guess_type(fpath.name)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{ctype or 'text/plain'}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        return True

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        qs = parse_qs(parsed.query)
        engine: OrchestratorEngine = self.server.engine  # type: ignore[attr-defined]

        try:
            if self._handle_static(path):
                return

            if path == "/api/projects":
                self._send_json(
                    200,
                    {
                        "projects": engine.list_projects(),
                        "fixtures": discover_fixtures(engine.base_dir),
                        "mock_mode": engine.is_mock_mode(),
                        "concurrency": engine.config.get("concurrency", {}),
                    },
                )
                return

            m = re.match(r"^/api/projects/([^/]+)/session$", path)
            if m:
                pid = m.group(1)
                sess = engine.get_session(pid)
                self._send_json(
                    200,
                    {
                        "session": sess.model_dump(mode="json"),
                        "mock_mode": engine.is_mock_mode(),
                        "concurrency": engine.config.get("concurrency", {}),
                        "events_tail": engine.store.read_events(pid, max(0, sess.last_event_seq - 60)),
                    },
                )
                return

            m = re.match(r"^/api/projects/([^/]+)/graph$", path)
            if m:
                pid = m.group(1)
                sess = engine.get_session(pid)
                self._send_json(
                    200,
                    {
                        "project_id": pid,
                        "spec_version": sess.spec_version,
                        "project_state": sess.project_state.value,
                        "tasks": [t.model_dump(mode="json") for t in sess.tasks.values()],
                        "edges": sess.edges,
                        "cpm": sess.cpm.model_dump(mode="json"),
                    },
                )
                return

            m = re.match(r"^/api/projects/([^/]+)/tasks/([^/]+)$", path)
            if m:
                pid, tid = m.group(1), m.group(2)
                self._send_json(200, engine.get_task_detail(pid, tid))
                return

            m = re.match(r"^/api/projects/([^/]+)/trace/([^/]+)$", path)
            if m:
                pid, tid = m.group(1), m.group(2)
                self._send_json(200, engine.build_task_trace(pid, tid))
                return

            m = re.match(r"^/api/projects/([^/]+)/events$", path)
            if m:
                pid = m.group(1)
                since = int((qs.get("since_seq") or ["0"])[0])
                self._send_json(200, {"events": engine.store.read_events(pid, since)})
                return

            m = re.match(r"^/api/projects/([^/]+)/events/stream$", path)
            if m:
                pid = m.group(1)
                self._serve_sse(pid, qs)
                return

            self._send_error_json(404, "ERR_NOT_FOUND", f"未找到路由: {path}")
        except OrchestratorError as exc:
            status = 404 if exc.code in ("ERR_PROJECT_NOT_FOUND", "ERR_TASK_NOT_FOUND") else 400
            self._send_error_json(status, exc.code, exc.message, exc.details)
        except Exception as exc:
            self._send_error_json(500, "ERR_INTERNAL", str(exc))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        engine: OrchestratorEngine = self.server.engine  # type: ignore[attr-defined]

        try:
            body = self._read_json_body()

            if path == "/api/projects/load":
                raw_dir = str(body.get("handoff_dir", "")).strip()
                if not raw_dir:
                    raise OrchestratorError("ERR_SCHEMA_INVALID", "缺少 handoff_dir 参数。")
                cand = Path(raw_dir)
                target = cand if cand.is_absolute() else (engine.base_dir / cand)
                sess, mode = engine.load_project(
                    target,
                    force_new_project=bool(body.get("force_new_project", False)),
                    auxiliary_mode=body.get("auxiliary_mode"),
                )
                self._send_json(200, {"load_mode": mode, "session": sess.model_dump(mode="json")})
                return

            m = re.match(r"^/api/projects/([^/]+)/gates/([^/]+)/decision$", path)
            if m:
                pid, gid = m.group(1), m.group(2)
                sess = engine.apply_gate_decision(
                    pid,
                    gid,
                    str(body.get("option", "")),
                    target=body.get("target"),
                    note=str(body.get("note", "")),
                    decided_by=str(body.get("decided_by", "human_director")),
                    payload=body.get("payload") or {},
                )
                self._send_json(200, {"session": sess.model_dump(mode="json")})
                return

            m = re.match(r"^/api/projects/([^/]+)/change-requests$", path)
            if m:
                pid = m.group(1)
                cr = engine.create_change_request(
                    pid,
                    trigger_source=str(body.get("trigger_source", "playtest_feedback")),
                    impacted_req_ids=list(body.get("impacted_req_ids", [])),
                    problem_statement=str(body.get("problem_statement", "")),
                    requested_delta=str(body.get("requested_delta", "")),
                )
                self._send_json(200, {"change_request": cr.model_dump(mode="json")})
                return

            m = re.match(r"^/api/projects/([^/]+)/control/([^/]+)$", path)
            if m:
                pid, action = m.group(1), m.group(2)
                res = engine.control(pid, action)
                self._send_json(200, res)
                return

            m = re.match(r"^/api/projects/([^/]+)/wave$", path)
            if m:
                pid = m.group(1)
                dispatched = engine.run_wave(pid)
                sess = engine.get_session(pid)
                self._send_json(200, {"dispatched": dispatched, "session": sess.model_dump(mode="json")})
                return

            m = re.match(r"^/api/projects/([^/]+)/demo/inject$", path)
            if m:
                pid = m.group(1)
                tid = str(body.get("task_id", ""))
                faults = list(body.get("faults", []))
                sess = engine.inject_demo_fault(pid, tid, faults)
                self._send_json(200, {"demo_faults": sess.demo_faults})
                return

            self._send_error_json(404, "ERR_NOT_FOUND", f"未找到路由: {path}")
        except OrchestratorError as exc:
            status = 404 if exc.code in ("ERR_PROJECT_NOT_FOUND", "ERR_TASK_NOT_FOUND") else 400
            self._send_error_json(status, exc.code, exc.message, exc.details)
        except Exception as exc:
            self._send_error_json(500, "ERR_INTERNAL", str(exc))

    def _serve_sse(self, project_id: str, qs: Dict[str, List[str]]) -> None:
        engine: OrchestratorEngine = self.server.engine  # type: ignore[attr-defined]
        engine.get_session(project_id)

        last_hdr = self.headers.get("Last-Event-ID")
        since_seq = int(last_hdr) if last_hdr and last_hdr.isdigit() else int((qs.get("since_seq") or ["0"])[0])

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        q: queue.Queue[Dict[str, Any]] = queue.Queue()

        def _on_evt(evt: Dict[str, Any]) -> None:
            if evt.get("project_id") == project_id:
                q.put(evt)

        engine.subscribe_sse(_on_evt)
        try:
            for hist in engine.store.read_events(project_id, since_seq):
                chunk = f"id: {hist['seq']}\nevent: {hist['event_type']}\ndata: {json.dumps(hist, ensure_ascii=False)}\n\n"
                self.wfile.write(chunk.encode("utf-8"))
                since_seq = max(since_seq, int(hist["seq"]))
            self.wfile.flush()

            while True:
                try:
                    evt = q.get(timeout=15.0)
                    if int(evt.get("seq", 0)) <= since_seq:
                        continue
                    since_seq = int(evt["seq"])
                    chunk = f"id: {evt['seq']}\nevent: {evt['event_type']}\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"
                    self.wfile.write(chunk.encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except Exception:
            pass
        finally:
            engine.unsubscribe_sse(_on_evt)
