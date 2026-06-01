"""
Contract Review Orchestrator — Main agent that reads contract text, determines
the review process, dispatches to specialist agents, and summarizes output.

The orchestrator:
  1. Runs the Extractor agent to produce a structured extraction
  2. Determines which specialist agents are relevant based on contract type
  3. Dispatches the extraction to each relevant specialist in parallel
  4. Runs the Risk Strategist to synthesize all findings
  5. Produces a customer-facing summary

Usage:
    from orchestrator import ContractReviewOrchestrator

    orch = ContractReviewOrchestrator(
        agents_dir="media_contracts_agents",
        model_id="us.anthropic.claude-sonnet-4-6",
        tools=[glossary_lookup, read_docx],
    )

    result = orch.review("path/to/contract.docx")
    print(result.summary)
"""

from __future__ import annotations

import json
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from strands import Agent
from strands.models.bedrock import BedrockModel

from utils.agent_factory import AgentFactory
from utils.pdf_to_images import PageImage, pdf_to_page_images


# ── S3 helpers ──────────────────────────────────────────────────────

_s3 = None


def _get_s3():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    """Parse s3://bucket/key into (bucket, key)."""
    if not uri.startswith("s3://"):
        raise ValueError(f"Not an S3 URI: {uri}")
    parts = uri[5:].split("/", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def _download_s3(uri: str, dest: str) -> None:
    bucket, key = _parse_s3_uri(uri)
    _get_s3().download_file(bucket, key, dest)


def _upload_s3(bucket: str, key: str, body: str | bytes) -> None:
    if isinstance(body, str):
        body = body.encode("utf-8")
    _get_s3().put_object(Bucket=bucket, Key=key, Body=body)


# ── Review result container ─────────────────────────────────────────

_FENCE_RE = re.compile(r"^```\w*\n?", re.MULTILINE)


def _strip_fences(text: str) -> str:
    """Remove markdown code fences (```xml ... ```) from model output."""
    return _normalize_typography(_FENCE_RE.sub("", text).strip())


_TYPO_MAP = str.maketrans(
    {
        "\u2013": "-",  # en dash  → hyphen
        "\u2014": "-",  # em dash  → hyphen
        "\u2018": "'",  # left single curly quote
        "\u2019": "'",  # right single curly quote / apostrophe
        "\u201c": '"',  # left double curly quote
        "\u201d": '"',  # right double curly quote
        "\u2026": "...",  # ellipsis
        "\u00a0": " ",  # non-breaking space
        "\u200b": "",  # zero-width space
        "\u2009": " ",  # thin space
        "\u202f": " ",  # narrow no-break space
    }
)


def _normalize_typography(text: str) -> str:
    """Replace typographic Unicode characters with ASCII equivalents."""
    return text.translate(_TYPO_MAP)


_TAG_RE = re.compile(r"<tag>([^<]+)</tag>")


def _extract_xml_tags(content: str) -> list[str]:
    """Extract <tag> values from a <tags> block in XML content."""
    return [m.group(1).strip() for m in _TAG_RE.finditer(content)]


@dataclass
class ReviewResult:
    """Container for the full pipeline output."""

    contract_path: str
    extraction: str = ""
    specialist_outputs: dict[str, str] = field(default_factory=dict)
    risk_synthesis: str = ""
    summary: str = ""
    agents_used: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)


# ── Contract type → relevant specialists mapping ────────────────────

# Which specialists to run based on contract type keywords in the extraction
_SPECIALIST_MAP: dict[str, list[str]] = {
    "distribution_agreement": [
        "financial",
        "rights_clearance",
        "talent_guild_compliance",
        "regulatory_compliance",
    ],
    "content_licensing_agreement": [
        "financial",
        "rights_clearance",
        "talent_guild_compliance",
        "regulatory_compliance",
    ],
    "talent_performance_agreement": [
        "financial",
        "rights_clearance",
        "talent_guild_compliance",
    ],
    "music_synchronization_license": [
        "financial",
        "rights_clearance",
    ],
    "digital_rights_ugc_license": [
        "financial",
        "rights_clearance",
        "regulatory_compliance",
    ],
}

# All specialists (fallback if contract type is unclear)
_ALL_SPECIALISTS = [
    "financial",
    "rights_clearance",
    "talent_guild_compliance",
    "regulatory_compliance",
]


def _detect_specialists(extraction_text: str) -> list[str]:
    """Determine which specialists to invoke based on extraction content."""
    text_lower = extraction_text.lower()
    for contract_type, specialists in _SPECIALIST_MAP.items():
        if contract_type.replace("_", " ") in text_lower:
            return specialists
    # Fallback: run all specialists
    return _ALL_SPECIALISTS


# ── Orchestrator ────────────────────────────────────────────────────


class ContractReviewOrchestrator:
    """Orchestrates the multi-agent contract review pipeline."""

    def __init__(
        self,
        agents_dir: str = "media_contracts_agents",
        model_id: str = "us.anthropic.claude-sonnet-4-6",
        max_tokens: int = 64000,
        tools: list[Any] | None = None,
        extraction_tools: list[Any] | None = None,
        analysis_tools: list[Any] | None = None,
        specialist_model_id: str | None = None,
        specialist_max_tokens: int = 16000,
        s3_output_bucket: str | None = None,
    ) -> None:
        self._factory = AgentFactory(
            agents_dir=agents_dir,
            model_id=model_id,
            max_tokens=max_tokens,
            tools=tools,
            extraction_tools=extraction_tools,
            analysis_tools=analysis_tools,
        )
        self._model_id = model_id
        self._max_tokens = max_tokens
        self._specialist_model_id = specialist_model_id
        self._specialist_max_tokens = specialist_max_tokens
        self._s3_output_bucket = s3_output_bucket

    def review(
        self,
        contract_path: str,
        specialists: list[str] | None = None,
        skip_risk_synthesis: bool = False,
        verbose: bool = True,
        on_progress: Any = None,
    ) -> ReviewResult:
        """
        Run the full review pipeline on a contract document.

        Args:
            contract_path: Path to the .docx or .txt contract file.
            specialists: Override which specialists to run (None = auto-detect).
            skip_risk_synthesis: If True, skip the Risk Strategist step.
            verbose: Print progress to stdout.
            on_progress: Optional callback(stage, status, detail, elapsed) for UI updates.
        """
        result = ReviewResult(contract_path=contract_path)

        # ── Resolve S3 input ────────────────────────────────────────
        local_contract_path = contract_path
        _tmp_file = None
        if contract_path.startswith("s3://"):
            _tmp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            _tmp_file.close()
            local_contract_path = _tmp_file.name
            if verbose:
                print(f"Downloading {contract_path} → {local_contract_path}")
            _download_s3(contract_path, local_contract_path)

        def _emit(stage, status, detail="", elapsed=None):
            if on_progress:
                on_progress(stage, status, detail, elapsed)

        # ── Step 1: Extraction ──────────────────────────────────────
        _emit("extractor", "running", "Extracting contract text")
        if verbose:
            print("=" * 60)
            print("STEP 1: Running Extractor agent...")
            print("=" * 60)

        t0 = time.perf_counter()

        page_extractions: dict[int, str] = {}

        if local_contract_path.lower().endswith(".pdf"):
            # Vision-based extraction: page-by-page parallel
            _emit("pdf_convert", "running", "Converting PDF to images")
            if verbose:
                print("  Converting PDF to page images...")
            pages = pdf_to_page_images(local_contract_path, dpi=128)
            _emit("pdf_convert", "done", f"{len(pages)} pages")
            _emit(
                "page_extraction",
                "running",
                f"Extracting {len(pages)} pages in parallel",
            )
            if verbose:
                print(f"  Rendered {len(pages)} pages — extracting in parallel...")

            def _extract_page(page: "PageImage") -> tuple[int, str, float]:
                pt0 = time.perf_counter()
                # Per-page extractor: no tools needed (vision-only), capped output
                model = BedrockModel(model_id=self._model_id, max_tokens=16000)
                agent = Agent(
                    model=model,
                    system_prompt=self._factory.get_prompt("extractor"),
                    tools=[],
                )
                content_blocks: list = [
                    {
                        "text": (
                            f"Extract all provisions from page {page.page_number} "
                            f"of this contract. Analyze the page image visually — "
                            f"read all text, tables, signatures, annotations, and "
                            f"formatting directly from the image. "
                            f"Output only the extraction for this single page."
                        )
                    },
                    {
                        "image": {
                            "format": page.format,
                            "source": {"bytes": page.image_bytes},
                        }
                    },
                ]
                response = agent(content_blocks)
                return page.page_number, str(response), time.perf_counter() - pt0

            with ThreadPoolExecutor(max_workers=min(len(pages), 8)) as pool:
                futures = {pool.submit(_extract_page, p): p for p in pages}
                for future in as_completed(futures):
                    page_num, output, elapsed = future.result()
                    page_extractions[page_num] = output
                    if verbose:
                        print(f"    ✓ Page {page_num} ({elapsed:.1f}s)")

            # Save per-page extractions to disk
            contract_name = Path(contract_path).stem
            pages_dir = Path("outputs") / contract_name / "pages"
            pages_dir.mkdir(parents=True, exist_ok=True)
            for page_num in sorted(page_extractions):
                page_file = pages_dir / f"page_{page_num:03d}.xml"
                page_file.write_text(
                    _strip_fences(page_extractions[page_num]), encoding="utf-8"
                )
            if verbose:
                print(
                    f"  Saved {len(page_extractions)} page extractions to {pages_dir}"
                )
            _emit("page_extraction", "done", f"{len(page_extractions)} pages extracted")

            # Concatenate page extractions in order — no LLM aggregation.
            # Specialists receive the full per-page output directly.
            ordered = [page_extractions[k] for k in sorted(page_extractions)]
            parts = []
            for i, text in enumerate(ordered, 1):
                parts.append(f"=== PAGE {i} EXTRACTION ===\n{text}")
            extraction_response = "\n\n".join(parts)
        else:
            # Non-PDF (docx, txt): use tool-based extraction as before
            extractor = self._factory.create("extractor")
            extraction_response = extractor(
                f"Extract all provisions from the contract document at: {local_contract_path}"
            )

        result.extraction = str(extraction_response)
        result.agents_used.append("extractor")
        result.timings["extractor"] = time.perf_counter() - t0
        _emit("extractor", "done", "", result.timings["extractor"])

        if verbose:
            print(f"  Extraction complete ({result.timings['extractor']:.1f}s)")

        # ── Step 2: Determine specialists ───────────────────────────
        if specialists is None:
            specialists = _detect_specialists(result.extraction)

        if verbose:
            print(f"\nSpecialists selected: {specialists}")

        # ── Step 3: Run specialists (parallel) ──────────────────────
        if verbose:
            spec_model = self._specialist_model_id or self._model_id
            print(f"\n{'=' * 60}")
            print(f"STEP 2: Running {len(specialists)} specialists in parallel...")
            print(f"  Launching: {', '.join(specialists)}")
            print(f"  Model: {spec_model} (max_tokens={self._specialist_max_tokens})")
            print("=" * 60)

        def _run_specialist(agent_name: str) -> tuple[str, str, float]:
            t0 = time.perf_counter()
            _emit(agent_name, "running")
            agent = self._factory.create(
                agent_name,
                model_id=self._specialist_model_id,
                max_tokens=self._specialist_max_tokens,
            )
            response = agent(
                f"Analyze the following contract extraction:\n\n{result.extraction}"
            )
            return agent_name, str(response), time.perf_counter() - t0

        with ThreadPoolExecutor(max_workers=len(specialists)) as pool:
            spec_futures = {
                pool.submit(_run_specialist, name): name for name in specialists
            }
            for spec_future in as_completed(spec_futures):
                agent_name, output, elapsed = spec_future.result()
                result.specialist_outputs[agent_name] = output
                result.agents_used.append(agent_name)
                result.timings[agent_name] = elapsed
                _emit(agent_name, "done", "", elapsed)
                if verbose:
                    print(f"  ✓ {agent_name} complete ({elapsed:.1f}s)")

        # ── Step 4: Risk Strategist synthesis ───────────────────────
        if not skip_risk_synthesis:
            if verbose:
                print(f"\n{'=' * 60}")
                print("STEP 3: Running Risk Strategist (synthesis)...")
                print("=" * 60)

            t0 = time.perf_counter()
            _emit("risk_strategist", "running", "Synthesizing risk assessment")
            risk_agent = self._factory.create("risk_strategist")

            # Build the synthesis input with all upstream outputs
            synthesis_input = self._build_synthesis_input(result)
            risk_response = risk_agent(synthesis_input)
            result.risk_synthesis = str(risk_response)
            result.agents_used.append("risk_strategist")
            result.timings["risk_strategist"] = time.perf_counter() - t0
            _emit("risk_strategist", "done", "", result.timings["risk_strategist"])

            if verbose:
                print(
                    f"  Risk synthesis complete ({result.timings['risk_strategist']:.1f}s)"
                )

        # ── Step 5: Customer summary ────────────────────────────────
        if verbose:
            print(f"\n{'=' * 60}")
            print("STEP 4: Generating customer summary...")
            print("=" * 60)

        t0 = time.perf_counter()
        _emit("summary", "running", "Generating executive summary")
        result.summary = self._generate_summary(result)
        result.timings["summary"] = time.perf_counter() - t0
        _emit("summary", "done", "", result.timings["summary"])

        if verbose:
            total = sum(result.timings.values())
            print(f"  Summary complete ({result.timings['summary']:.1f}s)")
            print(f"\nTotal pipeline time: {total:.1f}s")
            print(f"Agents used: {result.agents_used}")

        # ── Save outputs to disk ────────────────────────────────────
        contract_name = Path(contract_path).stem
        out_dir = Path("outputs") / contract_name
        out_dir.mkdir(parents=True, exist_ok=True)

        # Specialist outputs
        specialists_dir = out_dir / "specialists"
        specialists_dir.mkdir(exist_ok=True)
        for agent_name, output in result.specialist_outputs.items():
            (specialists_dir / f"{agent_name}.xml").write_text(
                _strip_fences(output), encoding="utf-8"
            )

        # Risk synthesis
        if result.risk_synthesis:
            (out_dir / "risk_synthesis.xml").write_text(
                _strip_fences(result.risk_synthesis), encoding="utf-8"
            )

        # Final summary
        if result.summary:
            (out_dir / "final-executive-summary.md").write_text(
                result.summary, encoding="utf-8"
            )

        # Timings
        (out_dir / "timings.json").write_text(
            json.dumps(result.timings, indent=2), encoding="utf-8"
        )

        if verbose:
            print(f"Outputs saved to {out_dir}/")

        # ── Upload to S3 knowledge base bucket ──────────────────────
        if self._s3_output_bucket:
            from agentcore.shared import kb_writer

            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            s3_prefix = f"{contract_name}_{ts}"

            # Collect all files to upload: (relative_key, content, kind)
            # Relative key is below <prefix>/<s3_prefix>/ (no leading slash).
            uploads: list[tuple[str, str, str]] = []

            # Page extractions (XML)
            page_nums = sorted(page_extractions)
            total_pages = len(page_nums)
            page_relative_keys = []
            for page_num in page_nums:
                rel = f"pages/page_{page_num:03d}.xml"
                uploads.append((rel, _strip_fences(page_extractions[page_num]), "xml"))
                page_relative_keys.append(rel)

            # Specialist outputs (XML)
            specialist_canonical_keys = []
            for agent_name, output in result.specialist_outputs.items():
                rel = f"specialists/{agent_name}.xml"
                uploads.append((rel, _strip_fences(output), "xml"))
                specialist_canonical_keys.append(
                    kb_writer.canonical_key(s3_prefix, rel)
                )

            # Risk synthesis (XML)
            if result.risk_synthesis:
                uploads.append(
                    (
                        "risk_synthesis.xml",
                        _strip_fences(result.risk_synthesis),
                        "xml",
                    )
                )

            # Summary (Markdown)
            if result.summary:
                uploads.append(("final-executive-summary.md", result.summary, "md"))

            # Source PDF filename (last component of path)
            source_pdf = Path(contract_path).name

            # Bedrock KB STRING_LIST cap: 10 items max
            def _sl(values: list[str]) -> dict:
                return {"stringListValue": values[:10], "type": "STRING_LIST"}

            # Base metadata attributes for every file in this job
            base_metadata = {
                "contract_name": {"stringValue": contract_name, "type": "STRING"},
                "source_uri": {"stringValue": contract_path, "type": "STRING"},
                "source_pdf": {"stringValue": source_pdf, "type": "STRING"},
                "analyzed_at": {"stringValue": ts, "type": "STRING"},
                "agents_used": _sl(result.agents_used),
                "total_time_seconds": {
                    "numberValue": round(sum(result.timings.values()), 1),
                    "type": "NUMBER",
                },
            }

            # Dual-prefix write: each (s3_key, content) becomes 4 PutObject calls
            # (canonical + KB + two metadata sidecars).
            for relative_key, content, kind in uploads:
                file_metadata = dict(base_metadata)

                # Page-specific metadata
                if relative_key in page_relative_keys:
                    page_idx = page_relative_keys.index(relative_key)
                    file_metadata["page_number"] = {
                        "numberValue": page_nums[page_idx],
                        "type": "NUMBER",
                    }
                    file_metadata["total_pages"] = {
                        "numberValue": total_pages,
                        "type": "NUMBER",
                    }

                # Tags from XML content (capped at 10)
                if kind == "xml":
                    tags = _extract_xml_tags(content)
                    if tags:
                        file_metadata["tags"] = _sl(tags)

                kb_writer.write_pair(
                    bucket=self._s3_output_bucket,
                    job_id=s3_prefix,
                    relative_key=relative_key,
                    content=content,
                    metadata_attributes=file_metadata,
                    kind=kind,
                )

            # Timings — canonical-only artifact (no KB copy, no sidecar)
            _upload_s3(
                self._s3_output_bucket,
                f"{kb_writer.CANONICAL_PREFIX}/{s3_prefix}/timings.json",
                json.dumps(result.timings, indent=2),
            )

            if verbose:
                print(
                    f"Uploaded {len(uploads)} files (canonical+KB) to "
                    f"s3://{self._s3_output_bucket}/"
                    f"{kb_writer.CANONICAL_PREFIX}/{s3_prefix}/ and "
                    f"{kb_writer.KB_PREFIX}/{s3_prefix}/"
                )

        # ── Cleanup temp file ───────────────────────────────────────
        if _tmp_file:
            import os

            os.unlink(_tmp_file.name)

        return result

    # ── Internal helpers ────────────────────────────────────────────

    def _build_synthesis_input(self, result: ReviewResult) -> str:
        """Build the input prompt for the Risk Strategist from all upstream outputs."""
        parts = [
            "You are receiving the outputs of the full contract analysis pipeline.",
            "Synthesize these into your risk assessment and negotiation roadmap.",
            "",
            "=== EXTRACTOR OUTPUT ===",
            result.extraction,
        ]
        for agent_name, output in result.specialist_outputs.items():
            label = agent_name.upper().replace("_", " ")
            parts.append(f"\n=== {label} OUTPUT ===")
            parts.append(output)

        return "\n".join(parts)

    def _generate_summary(self, result: ReviewResult) -> str:
        """Generate a customer-facing summary using a lightweight agent call."""
        model = BedrockModel(model_id=self._model_id, max_tokens=self._max_tokens)
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

        # Use risk synthesis if available, otherwise use specialist outputs
        analysis = result.risk_synthesis or "\n\n".join(
            f"[{k}]: {v}" for k, v in result.specialist_outputs.items()
        )

        response = summary_agent(
            f"Summarize this contract analysis for the customer:\n\n{analysis}"
        )
        return str(response)

    def __repr__(self) -> str:
        return f"ContractReviewOrchestrator(model={self._model_id}, agents={self._factory.list_agents()})"
