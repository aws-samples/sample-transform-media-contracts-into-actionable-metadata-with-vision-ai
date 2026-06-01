"""Strands Agent lifecycle logging hooks for MediaContracts.

Attaches to BeforeToolCall, AfterToolCall, BeforeModelCall, AfterModelCall,
BeforeInvocation, and AfterInvocation events to produce structured JSON logs
visible in CloudWatch Logs Insights.

Usage:
    from agentcore.shared.logging_hooks import AgentLoggingHooks

    agent = Agent(
        model=model,
        tools=tools,
        hooks=[AgentLoggingHooks(job_id="abc-123", agent_name="orchestrator")],
    )
"""

from __future__ import annotations

import logging
import time
from typing import Any

from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import (
    AfterInvocationEvent,
    AfterModelCallEvent,
    AfterToolCallEvent,
    BeforeInvocationEvent,
    BeforeModelCallEvent,
    BeforeToolCallEvent,
)

logger = logging.getLogger("orchestrator")


class AgentLoggingHooks(HookProvider):
    """Logs every lifecycle event in the Strands agent loop.

    Produces structured key=value logs that the JsonFormatter in
    logging_config.py will parse into queryable CloudWatch fields.
    """

    def __init__(self, job_id: str = "", agent_name: str = "orchestrator") -> None:
        self.job_id = job_id
        self.agent_name = agent_name
        self._invocation_start: float = 0.0
        self._model_call_start: float = 0.0
        self._model_call_count: int = 0
        self._tool_call_start: float = 0.0
        self._tool_call_count: int = 0

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeInvocationEvent, self._before_invocation)  # type: ignore[arg-type]
        registry.add_callback(AfterInvocationEvent, self._after_invocation)  # type: ignore[arg-type]
        registry.add_callback(BeforeModelCallEvent, self._before_model_call)  # type: ignore[arg-type]
        registry.add_callback(AfterModelCallEvent, self._after_model_call)  # type: ignore[arg-type]
        registry.add_callback(BeforeToolCallEvent, self._before_tool_call)  # type: ignore[arg-type]
        registry.add_callback(AfterToolCallEvent, self._after_tool_call)  # type: ignore[arg-type]

    # ── Invocation lifecycle ───────────────────────────────────────

    def _before_invocation(self, _event: BeforeInvocationEvent) -> None:
        self._invocation_start = time.perf_counter()
        self._model_call_count = 0
        self._tool_call_count = 0
        logger.info(
            "job=%s agent=%s event=before_invocation",
            self.job_id,
            self.agent_name,
        )

    def _after_invocation(self, event: AfterInvocationEvent) -> None:
        elapsed = (
            time.perf_counter() - self._invocation_start
            if self._invocation_start
            else 0
        )
        stop_reason = ""
        result = getattr(event, "result", None)
        if result is not None and hasattr(result, "stop_reason"):
            stop_reason = str(result.stop_reason)
        logger.info(
            "job=%s agent=%s event=after_invocation elapsed=%.1fs "
            "model_calls=%d tool_calls=%d stop_reason=%s",
            self.job_id,
            self.agent_name,
            elapsed,
            self._model_call_count,
            self._tool_call_count,
            stop_reason,
        )

    # ── Model call lifecycle ───────────────────────────────────────

    def _before_model_call(self, _event: BeforeModelCallEvent) -> None:
        self._model_call_start = time.perf_counter()
        self._model_call_count += 1
        logger.info(
            "job=%s agent=%s event=before_model_call call_number=%d",
            self.job_id,
            self.agent_name,
            self._model_call_count,
        )

    def _after_model_call(self, event: AfterModelCallEvent) -> None:
        elapsed = (
            time.perf_counter() - self._model_call_start
            if self._model_call_start
            else 0
        )

        if event.exception:
            logger.error(
                "job=%s agent=%s event=after_model_call call_number=%d "
                "elapsed=%.1fs status=error error=%s",
                self.job_id,
                self.agent_name,
                self._model_call_count,
                elapsed,
                event.exception,
            )
            return

        stop_reason = ""
        if event.stop_response:
            stop_reason = str(event.stop_response.stop_reason)

        logger.info(
            "job=%s agent=%s event=after_model_call call_number=%d "
            "elapsed=%.1fs stop_reason=%s",
            self.job_id,
            self.agent_name,
            self._model_call_count,
            elapsed,
            stop_reason,
        )

    # ── Tool call lifecycle ────────────────────────────────────────

    def _before_tool_call(self, event: BeforeToolCallEvent) -> None:
        self._tool_call_start = time.perf_counter()
        self._tool_call_count += 1
        tool_name = (
            event.tool_use.get("name", "unknown") if event.tool_use else "unknown"
        )
        tool_id = event.tool_use.get("toolUseId", "") if event.tool_use else ""
        logger.info(
            "job=%s agent=%s event=before_tool_call tool=%s tool_id=%s call_number=%d",
            self.job_id,
            self.agent_name,
            tool_name,
            tool_id,
            self._tool_call_count,
        )

    def _after_tool_call(self, event: AfterToolCallEvent) -> None:
        elapsed = (
            time.perf_counter() - self._tool_call_start if self._tool_call_start else 0
        )
        tool_name = (
            event.tool_use.get("name", "unknown") if event.tool_use else "unknown"
        )
        tool_id = event.tool_use.get("toolUseId", "") if event.tool_use else ""

        status = "success"
        error_msg = ""
        if isinstance(event.result, Exception):
            status = "error"
            error_msg = str(event.result)
        elif event.cancel_message:
            status = "cancelled"
            error_msg = str(event.cancel_message)

        logger.info(
            "job=%s agent=%s event=after_tool_call tool=%s tool_id=%s "
            "elapsed=%.1fs status=%s",
            self.job_id,
            self.agent_name,
            tool_name,
            tool_id,
            elapsed,
            status,
        )
        if error_msg:
            logger.warning(
                "job=%s agent=%s tool=%s error=%s",
                self.job_id,
                self.agent_name,
                tool_name,
                error_msg[:500],
            )
