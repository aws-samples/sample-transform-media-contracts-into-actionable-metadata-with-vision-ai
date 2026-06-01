"""Dual-prefix result writer for Bedrock KB ingestion.

The results bucket layout is:

    jobs-canonical-versions/<job_id>/...
        Originals — XML and Markdown files kept as-is.

    jobs-kb-versions/<job_id>/...
        Knowledge-Base-friendly copies. XML is rewritten to plain text
        (the leading <?xml ... ?> declaration is stripped so Bedrock KB
        can index it; Markdown is copied verbatim).
        Every object here has a companion <key>.metadata.json sidecar
        that contains Bedrock KB metadata attributes.

Use `write_pair` for a single logical output and `KB_PREFIX` / `CANONICAL_PREFIX`
constants for constructing keys yourself.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Mapping

import boto3

logger = logging.getLogger(__name__)

CANONICAL_PREFIX = "jobs-canonical-versions"
KB_PREFIX = "jobs-kb-versions"

# Matches an XML declaration at the start of a document (optionally with BOM).
_XML_DECL_RE = re.compile(r"^\s*<\?xml[^?]*\?>\s*", re.DOTALL)


def strip_xml_declaration(content: str) -> str:
    """Remove a leading XML declaration so Bedrock KB can index the file as text."""
    return _XML_DECL_RE.sub("", content, count=1)


def kb_metadata_sidecar(attributes: Mapping[str, Any]) -> str:
    """Serialize Bedrock KB metadata attributes into the sidecar JSON format.

    Callers pass a dict of attribute definitions using the internal format:
        {attribute_name: {type, stringValue|numberValue|stringListValue, ...}}

    This helper converts them to the Bedrock KB sidecar format:
        {metadataAttributes: {name: {value: {type, stringValue|...}, includeForEmbedding}}}

    STRING_LIST is not supported in sidecar metadata — lists are joined with "; ".
    """
    sidecar_attrs: dict[str, Any] = {}
    for name, attr in attributes.items():
        attr_type = attr.get("type", "STRING")

        if attr_type == "STRING":
            sidecar_attrs[name] = {
                "value": {
                    "type": "STRING",
                    "stringValue": str(attr.get("stringValue", "")),
                },
                "includeForEmbedding": True,
            }
        elif attr_type == "NUMBER":
            sidecar_attrs[name] = {
                "value": {"type": "NUMBER", "numberValue": attr.get("numberValue", 0)},
                "includeForEmbedding": False,
            }
        elif attr_type == "BOOLEAN":
            sidecar_attrs[name] = {
                "value": {
                    "type": "BOOLEAN",
                    "booleanValue": attr.get("booleanValue", False),
                },
                "includeForEmbedding": False,
            }
        elif attr_type == "STRING_LIST":
            # STRING_LIST not supported in sidecar format — flatten to semicolon-separated string
            items = attr.get("stringListValue", [])
            sidecar_attrs[name] = {
                "value": {"type": "STRING", "stringValue": "; ".join(items)},
                "includeForEmbedding": True,
            }
        else:
            # Fallback: treat as string
            sidecar_attrs[name] = {
                "value": {
                    "type": "STRING",
                    "stringValue": str(attr.get("stringValue", "")),
                },
                "includeForEmbedding": True,
            }

    return json.dumps({"metadataAttributes": sidecar_attrs}, indent=2)


def canonical_key(job_id: str, relative_key: str) -> str:
    """Build a canonical-prefix S3 key for a given job."""
    return f"{CANONICAL_PREFIX}/{job_id.strip('/')}/{relative_key.lstrip('/')}"


def kb_key(job_id: str, relative_key: str) -> str:
    """Build a KB-prefix S3 key for a given job."""
    return f"{KB_PREFIX}/{job_id.strip('/')}/{relative_key.lstrip('/')}"


def _put(s3_client, bucket: str, key: str, body: str) -> None:
    s3_client.put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"))


def write_pair(
    bucket: str,
    job_id: str,
    relative_key: str,
    content: str,
    metadata_attributes: Mapping[str, Any],
    *,
    kind: str,
    s3_client=None,
) -> dict[str, str]:
    """Write one logical output to both the canonical and KB prefixes.

    Args:
        bucket: Results bucket name.
        job_id: Job identifier (S3 path segment).
        relative_key: Path below the `<prefix>/<job_id>/` directory, e.g.
            ``"specialists/financial.xml"`` or ``"final-executive-summary.md"``.
        content: File contents as a UTF-8 string.
        metadata_attributes: Bedrock KB metadata attribute dict (no outer envelope).
        kind: ``"xml"`` or ``"md"``. XML content gets its declaration stripped
            and the KB-side extension rewritten to ``.txt``. Markdown is copied
            verbatim with the ``.md`` extension preserved.
        s3_client: Optional boto3 S3 client to reuse.

    Returns:
        A dict with the four S3 keys written: ``canonical_key``,
        ``canonical_metadata_key``, ``kb_key``, ``kb_metadata_key``.
    """
    if kind not in ("xml", "md"):
        raise ValueError(f"kind must be 'xml' or 'md', got {kind!r}")

    s3 = s3_client or boto3.client("s3")

    # Canonical side: exact content, .xml or .md extension preserved.
    can_key = canonical_key(job_id, relative_key)
    can_meta_key = f"{can_key}.metadata.json"

    # KB side: for XML, strip declaration and switch to .txt.
    if kind == "xml":
        kb_relative = (
            relative_key[:-4] + ".txt"
            if relative_key.endswith(".xml")
            else relative_key
        )
        kb_content = strip_xml_declaration(content)
    else:
        kb_relative = relative_key
        kb_content = content
    kb_obj_key = kb_key(job_id, kb_relative)
    kb_meta_key = f"{kb_obj_key}.metadata.json"

    sidecar = kb_metadata_sidecar(metadata_attributes)

    _put(s3, bucket, can_key, content)
    _put(s3, bucket, can_meta_key, sidecar)
    _put(s3, bucket, kb_obj_key, kb_content)
    _put(s3, bucket, kb_meta_key, sidecar)

    logger.debug("Wrote dual-prefix output: canonical=%s kb=%s", can_key, kb_obj_key)

    return {
        "canonical_key": can_key,
        "canonical_metadata_key": can_meta_key,
        "kb_key": kb_obj_key,
        "kb_metadata_key": kb_meta_key,
    }
