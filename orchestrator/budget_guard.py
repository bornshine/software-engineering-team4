from __future__ import annotations

import re
import time
from typing import Any, Callable, Dict, List, Optional, Pattern, Tuple, TypeVar

from .schemas import BudgetState, OrchestratorError

T = TypeVar("T")

DEFAULT_REDACT_PATTERNS = [
    r"sk-[A-Za-z0-9_-]{16,}",
    r"ghp_[A-Za-z0-9]{20,}",
    r"AKIA[0-9A-Z]{16}",
]


class BudgetGuard:
    """§7.5 执行安全与预算守卫：费用/调用上限控制、退避重试与日志密钥脱敏。"""

    def __init__(self, patterns: Optional[List[str]] = None) -> None:
        raw_patterns = patterns or DEFAULT_REDACT_PATTERNS
        self._compiled: List[Pattern[str]] = [re.compile(p) for p in raw_patterns]

    def can_dispatch(self, budget: BudgetState) -> Tuple[bool, str]:
        if budget.cost_used >= budget.cost_cap > 0:
            return False, f"项目费用已达上限 ({budget.cost_used:.4f} >= {budget.cost_cap:.4f})"
        if budget.calls_used >= budget.calls_cap > 0:
            return False, f"模型调用次数已达上限 ({budget.calls_used} >= {budget.calls_cap})"
        return True, ""

    def record_usage(self, budget: BudgetState, *, calls: int, cost: float) -> bool:
        """累计一次尝试的资源消耗；超出项目预算返回 False。"""
        budget.calls_used += max(0, int(calls))
        budget.cost_used = round(budget.cost_used + max(0.0, float(cost)), 6)
        ok, _ = self.can_dispatch(budget)
        return ok

    def redact_text(self, text: str) -> str:
        out = text
        for pat in self._compiled:
            out = pat.sub(lambda m: f"{m.group(0)[:4]}***REDACTED***", out)
        return out

    def redact_obj(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, list):
            return [self.redact_obj(v) for v in value]
        if isinstance(value, dict):
            return {k: self.redact_obj(v) for k, v in value.items()}
        return value


def call_with_backoff(
    fn: Callable[[], T],
    *,
    max_retries: int = 3,
    base_sec: float = 2.0,
    should_retry: Optional[Callable[[Exception], bool]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> T:
    """对 429 / 5xx / 超时执行指数退避（退避重试不计入任务 attempts_failed）。"""
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:
            if attempt >= max_retries or (should_retry and not should_retry(exc)):
                raise
            delay = base_sec * (2**attempt)
            sleep_fn(delay)
            attempt += 1
