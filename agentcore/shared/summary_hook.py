"""Post-invocation hook that generates the executive summary.

After the orchestrator agent finishes its tool calls (specialists write
their own outputs to S3), this hook:
  1. Reads all specialist outputs from the S3 results prefix
  2. Generates an executive summary via a standalone Bedrock Converse call
  3. Writes the summary to both canonical and KB prefixes

This decouples summary generation from the orchestrator agent's lifecycle.
Even if the agent's conversational response is thin or the runtime is under
time pressure, the specialist outputs are already in S3 and the summary
can be generated independently.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import boto3
from strands import Agent
from strands.hooks import HookProvider, HookRegistry
from strands.hooks.events import AfterInvocationEvent

from agentcore.shared import kb_writer
from agentcore.shared.bedrock_client import make_model

logger = logging.getLogger("orchestrator")


class SummaryGenerationHook(HookProvider):
    """Generates and writes the executive summary after the orchestrator agent completes."""

    def __init__(
        self,
        job_id: str,
        s3_prefix: str,
        results_bucket: str,
        model_id: str,
        agents_used: list[str],
        timings: dict[str, float],
    ) -> None:
        self.job_id = job_id
        self.s3_prefix = s3_prefix
        self.results_bucket = results_bucket
        self.model_id = model_id
        self.agents_used = agents_used
        self.timings = timings
        self._s3 = boto3.client("s3")

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(AfterInvocationEvent, self._after_invocation)

    def _after_invocation(self, event: AfterInvocationEvent) -> None:
        """Read specialist outputs from S3, generate summary, write to both prefixes."""
        logger.info("job=%s hook=summary_generation step=start", self.job_id)
        t0 = time.perf_counter()

        try:
            # Read specialist outputs from S3 (already written by Lambda specialists)
            specialist_content = self._read_specialist_outputs()
            if not specialist_content:
                logger.warning(
                    "job=%s hook=summary_generation no specialist outputs found in S3",
                    self.job_id,
                )
                return

            # Generate executive summary
            summary = self._generate_summary(specialist_content)

            # Write to S3 (dual-prefix: canonical + KB)
            self._write_summary(summary)

            elapsed = time.perf_counter() - t0
            self.timings["summary"] = elapsed
            self.agents_used.append("summary")
            logger.info(
                "job=%s hook=summary_generation step=complete elapsed=%.1fs output_len=%d",
                self.job_id,
                elapsed,
                len(summary),
            )

        except Exception as e:
            logger.error(
                "job=%s hook=summary_generation FAILED: %s",
                self.job_id,
                e,
                exc_info=True,
            )
            raise

    def _read_specialist_outputs(self) -> str:
        """Read all specialist XML outputs and risk synthesis from S3."""
        prefix = f"{kb_writer.CANONICAL_PREFIX}/{self.s3_prefix}/specialists/"
        parts: list[str] = []

        # List specialist files
        resp = self._s3.list_objects_v2(Bucket=self.results_bucket, Prefix=prefix)
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".metadata.json"):
                continue
            try:
                body = (
                    self._s3.get_object(Bucket=self.results_bucket, Key=key)["Body"]
                    .read()
                    .decode("utf-8")
                )
                specialist_name = key.split("/")[-1].replace(".xml", "")
                parts.append(f"[{specialist_name}]:\n{body}")
            except Exception as e:
                logger.warning(
                    "job=%s hook=summary_generation failed to read %s: %s",
                    self.job_id,
                    key,
                    e,
                )

        # Also read risk synthesis if present
        risk_key = f"{kb_writer.CANONICAL_PREFIX}/{self.s3_prefix}/risk_synthesis.xml"
        try:
            body = (
                self._s3.get_object(Bucket=self.results_bucket, Key=risk_key)["Body"]
                .read()
                .decode("utf-8")
            )
            parts.append(f"[risk_synthesis]:\n{body}")
        except self._s3.exceptions.NoSuchKey:
            pass
        except Exception as e:
            logger.warning(
                "job=%s hook=summary_generation failed to read risk_synthesis: %s",
                self.job_id,
                e,
            )

        return "\n\n".join(parts)

    def _generate_summary(self, specialist_content: str) -> str:
        """Generate executive summary via a standalone Bedrock call."""
        model = make_model(self.model_id, 64000)
        summary_agent = Agent(
            model=model,
            system_prompt=(
                "You are a senior media business affairs advisor. "
                "Produce a clear, actionable executive summary of a contract review. "
                "Structure it as: (1) Contract Overview, (2) Key Findings, "
                "(3) Top Risks, (4) Recommended Actions. "
                "Write for a non-lawyer executive audience. Be concise."
            ),
            tools=[],
        )
        return str(
            summary_agent(
                f"Summarize this contract analysis for the customer:\n\n{specialist_content}"
            )
        )

    def _write_summary(self, summary: str) -> None:
        """Write executive summary to both canonical and KB prefixes."""
        summary_metadata = {
            "job_id": {"stringValue": self.job_id, "type": "STRING"},
            "kind": {"stringValue": "final_executive_summary", "type": "STRING"},
            "analyzed_at": {
                "stringValue": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "type": "STRING",
            },
            "agents_used": {
                "stringListValue": self.agents_used[:10],
                "type": "STRING_LIST",
            },
        }
        kb_writer.write_pair(
            bucket=self.results_bucket,
            job_id=self.s3_prefix,
            relative_key="final-executive-summary.md",
            content=summary,
            metadata_attributes=summary_metadata,
            kind="md",
            s3_client=self._s3,
        )
        logger.info(
            "job=%s hook=summary_generation wrote final-executive-summary.md to both prefixes",
            self.job_id,
        )
