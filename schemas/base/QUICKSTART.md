# MCS v1.0 Quick Start Guide

## What is MCS?

**Media Contracts Schema (MCS) v1.0** is the standardized XML response format for all contract analysis agents. It provides a consistent structure while allowing each analyzer to define its own domain-specific content.

## Files

- **[mcs_base_schema.xml](mcs_base_schema.xml)** - The base schema with all 7 parts fully documented
- **[README.md](README.md)** - Complete documentation and guidelines
- **[IMPLEMENTATION_MATRIX.md](IMPLEMENTATION_MATRIX.md)** - Quick reference for which parts each analyzer uses
- **[validate_mcs.py](validate_mcs.py)** - Python validator to check conformance

## Quick Validation

Check if all format files conform to MCS:

```bash
python3 schemas/base/validate_mcs.py media_contracts_agents/
```

Check a single file:

```bash
python3 schemas/base/validate_mcs.py media_contracts_agents/financial/financial_format.xml
```

## The 7 Parts of MCS

| Part | Name | Required For | Description |
|------|------|--------------|-------------|
| **1** | Envelope | All | Root `<response>` with analyzer, schema_version, job_id, timestamp |
| **2** | Core Metadata | All | Standard metadata fields (analyzer_name, timestamp, confidence, etc.) |
| **3** | Common Spine | Document analyzers | Ordered text elements for reconstruction (extractor, handwriting_analyzer) |
| **4** | Topical Analysis | Optional | High-level topic summary |
| **5** | Specialized | All | Domain-specific analysis structure (unique per analyzer) |
| **6** | Findings | Specialist analyzers | Risks, gaps, ambiguities (not used by extractor) |
| **7** | Tags | All | Topical categorization tags |

## Format File Structure

Every format file should have this structure:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!--
    {Analyzer Name} — Response Format
    ===================================
    Media Contracts Schema (MCS) v1.0
    Implements: Part 1 + Part 2 + Part 5 + Part 6 + Part 7
    See: schemas/base/mcs_base_schema.xml
-->
<response_format>
    <!-- MCS Part 1: Envelope -->
    <response analyzer="{analyzer_name}"
              schema_version="1.0"
              job_id="{JOB_ID}"
              timestamp="{ISO_8601_TIMESTAMP}">

        <!-- MCS Part 2: Core Metadata -->
        <metadata>
            <analyzer_name>{analyzer_name}</analyzer_name>
            <schema_version>1.0</schema_version>
            <timestamp>{ISO_8601_TIMESTAMP}</timestamp>
            <source_document>{DOCUMENT_TITLE}</source_document>
            <element_count>{COUNT}</element_count>
            <confidence>{high|medium|low}</confidence>
            <!-- Analyzer-specific fields... -->
        </metadata>

        <!-- MCS Part 3: Common Spine (if applicable) -->
        <common_spine element_count="{N}">
            <element id="elem_001" tag="P" order="1" page="1">
                <text>{CONTENT}</text>
            </element>
        </common_spine>

        <!-- MCS Part 4: Topical Analysis (optional) -->
        <topical_analysis>{TOPICS}</topical_analysis>

        <!-- MCS Part 5: Specialized Section -->
        <specialized type="{analyzer_type}">
            <!-- Analyzer-specific structure -->
        </specialized>

        <!-- MCS Part 6: Findings (if applicable) -->
        <{analyzer}_findings>
            <risks>...</risks>
            <gaps>...</gaps>
            <cross_references>...</cross_references>
        </{analyzer}_findings>

        <!-- MCS Part 7: Tags -->
        <tags>
            <tag>{TAG}</tag>
        </tags>

    </response>
</response_format>
```

## Current Status

All 7 analyzer format files are MCS v1.0 compliant:

✅ [extractor_format.xml](../../media_contracts_agents/extractor/extractor_format.xml)
✅ [handwriting_format.xml](../../media_contracts_agents/handwriting_analyzer/handwriting_format.xml)
✅ [financial_format.xml](../../media_contracts_agents/financial/financial_format.xml)
✅ [rights_format.xml](../../media_contracts_agents/rights_clearance/rights_format.xml)
✅ [regulatory_format.xml](../../media_contracts_agents/regulatory_compliance/regulatory_format.xml)
✅ [talent_format.xml](../../media_contracts_agents/talent_guild_compliance/talent_format.xml)
✅ [risk_format.xml](../../media_contracts_agents/risk_strategist/risk_format.xml)

## Adding a New Analyzer

1. Determine analyzer type (document or specialist)
2. Check [IMPLEMENTATION_MATRIX.md](IMPLEMENTATION_MATRIX.md) for required parts
3. Copy structure from a similar analyzer
4. Add MCS reference comment in header
5. Implement required parts with your domain-specific structure in Part 5
6. Validate with: `python3 schemas/base/validate_mcs.py path/to/your_format.xml`

## Benefits

- **Consistency** - All analyzers share standard envelope and metadata
- **Modularity** - Include only relevant parts for your analyzer type
- **Extensibility** - Add domain-specific fields without breaking the schema
- **Validation** - Automated checking ensures conformance
- **Documentation** - Self-documenting with inline comments
- **Correlation** - Downstream systems can reliably parse all outputs

## Questions?

See [README.md](README.md) for complete documentation or run the validator for specific errors.
