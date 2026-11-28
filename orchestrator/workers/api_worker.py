from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

from ..budget_guard import call_with_backoff
from ..handoff_loader import compute_file_sha256
from ..schemas import ArtifactFile, ArtifactManifest
from .base import WorkerResult


class ApiWorker:
    """
    §7.4 真实 LLM API Worker（OpenAI 兼容 Chat Completions 接口）：
    - 仅输出结构化 JSON 描述需要写入的文件清单及正文，由编排器落盘到尝试工作区；
    - 附带 429/5xx/超时指数退避，真实计费与调用计数由 BudgetGuard 拦截。
    """

    mode = "api"

    def __init__(
        self,
        role: str,
        *,
        model: str = "gpt-4o-mini",
        api_base: Optional[str] = None,
        api_key_env: str = "OPENAI_API_KEY",
        max_backoff_retries: int = 3,
        backoff_base_sec: float = 2.0,
    ) -> None:
        self.role = role
        self.model = model
        self.api_base = (api_base or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.api_key_env = api_key_env
        self.max_backoff_retries = max_backoff_retries
        self.backoff_base_sec = backoff_base_sec

    def run(self, ctx: Dict[str, Any], workdir: Path, timeout_sec: int) -> WorkerResult:
        started = time.perf_counter()
        api_key = os.environ.get(self.api_key_env, "").strip()
        if not api_key:
            return WorkerResult(
                ok=False,
                error_message=f"未检测到真实 API 密钥环境变量 {self.api_key_env}，请配置或启用 --mock 模式。",
                runtime_sec=round(time.perf_counter() - started, 4),
            )

        prompt_sys = (
            "你是 2D 风格化游戏工程的严格工种执行 Agent。"
            "严格只返回 JSON 对象：{\"files\": [{\"path\": \"...\", \"content\": \"...\"}], \"summary\": \"...\"}。"
            f"只能写入以下目录前缀之一: {ctx.get('writable_paths', [])}。"
        )
        prompt_user = json.dumps(ctx, ensure_ascii=False)
        body = json.dumps(
            {
                "model": self.model,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": prompt_sys},
                    {"role": "user", "content": prompt_user},
                ],
                "temperature": 0.2,
            }
        ).encode("utf-8")

        calls_made = 0

        def _invoke() -> Dict[str, Any]:
            nonlocal calls_made
            calls_made += 1
            req = urllib.request.Request(
                f"{self.api_base}/chat/completions",
                data=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=min(timeout_sec, 120)) as resp:
                return json.loads(resp.read().decode("utf-8"))

        def _retryable(exc: Exception) -> bool:
            if isinstance(exc, urllib.error.HTTPError):
                return exc.code == 429 or exc.code >= 500
            return isinstance(exc, (TimeoutError, urllib.error.URLError))

        try:
            raw_resp = call_with_backoff(
                _invoke,
                max_retries=self.max_backoff_retries,
                base_sec=self.backoff_base_sec,
                should_retry=_retryable,
            )
            content_text = raw_resp["choices"][0]["message"]["content"]
            parsed = json.loads(content_text)
        except Exception as exc:
            return WorkerResult(
                ok=False,
                error_message=f"API 调用或响应解析失败: {exc}",
                api_calls=calls_made,
                cost=round(calls_made * 0.02, 4),
                runtime_sec=round(time.perf_counter() - started, 4),
            )

        written: List[ArtifactFile] = []
        root_resolved = workdir.resolve()
        for fobj in parsed.get("files", []):
            rel = str(fobj["path"]).replace("\\", "/").lstrip("/")
            dest = (root_resolved / rel).resolve()
            if not dest.is_relative_to(root_resolved):
                return WorkerResult(
                    ok=False,
                    error_message=f"API 返回非法逃逸路径: {rel}",
                    api_calls=calls_made,
                    cost=round(calls_made * 0.02, 4),
                    runtime_sec=round(time.perf_counter() - started, 4),
                )
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(str(fobj.get("content", "")), encoding="utf-8", newline="\n")
            written.append(ArtifactFile(path=rel, sha256=compute_file_sha256(dest)))

        usage = raw_resp.get("usage", {})
        est_cost = round(
            (usage.get("prompt_tokens", 1000) * 0.000002) + (usage.get("completion_tokens", 500) * 0.000008),
            6,
        )
        return WorkerResult(
            ok=True,
            manifest=ArtifactManifest(
                task_id=ctx["task_id"],
                attempt=int(ctx.get("attempt", 1)),
                files=written,
                scenario_dispute=parsed.get("scenario_dispute"),
                summary=str(parsed.get("summary", "API Worker 产出完成")),
                api_calls=calls_made,
                cost=est_cost,
            ),
            api_calls=calls_made,
            cost=est_cost,
            runtime_sec=round(time.perf_counter() - started, 4),
        )
