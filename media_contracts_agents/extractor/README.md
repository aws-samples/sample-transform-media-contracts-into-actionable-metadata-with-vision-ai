# Extractor Agent

Document extraction analyzer that produces structured contract content for downstream specialists.

## Purpose

The extractor is the first-stage analyzer that extracts all contract components from the source PDF into a structured XML format. This extraction serves as the input for all downstream specialist analyzers.

## MCS Implementation

**Type**: Document Analyzer
**Format File**: [extractor_format.xml](extractor_format.xml)
**MCS Parts**: 1 (Envelope), 2 (Metadata), 3 (Common Spine), 4 (Topical Analysis), 5 (Specialized), 7 (Tags)

### Part 3: Common Spine

The extractor produces a **common_spine** containing all extracted text in reading order. Each section/paragraph becomes a spine element with:
- Unique ID (`elem_001`, `elem_002`, etc.)
- Structural tag (P, H1, H2, H3, Table, List)
- Order number
- Page reference

This spine allows downstream consumers to reconstruct the document and correlate findings back to source text.

### Part 5: Specialized Section

The `<specialized type="extraction">` section contains comprehensive extraction of:

- **Parties**: All contracting parties with legal names, roles, entity types
- **Defined Terms**: All definitions with exact locations
- **Rights Grant**: Specific rights, territories, platforms, language rights
- **Financial Terms**: Fixed compensation, revenue share, MG, residuals, expenses
- **Term & Termination**: Initial term, renewal, termination triggers
- **Obligations**: Delivery requirements, exclusivity, approval rights
- **Talent & Third Party**: Guild compliance, music licensing, embedded IP
- **Credit & Attribution**: Screen credits, paid advertising requirements
- **Legal Protections**: Warranties, indemnification, liability, insurance
- **Digital & Emerging Rights**: AI, NFT, metaverse, social media
- **Regulatory**: Content ratings, accessibility, data protection
- **Exhibits & Signatures**: Attached schedules, signature blocks

### No Findings Section

The extractor is **extraction-only** and does not produce a findings section (Part 6). Analysis is performed by downstream specialists.

## Output Structure

```xml
<response analyzer="extractor" schema_version="1.0" job_id="{ID}" timestamp="{ISO}">
    <metadata>
        <analyzer_name>extractor</analyzer_name>
        <contract_type>CONTENT_LICENSE|TALENT_AGREEMENT|...</contract_type>
        <page_count>{N}</page_count>
        <blank_field_count>{N}</blank_field_count>
        ...
    </metadata>

    <common_spine element_count="{N}">
        <element id="elem_001" tag="H1" order="1" page="1">
            <text>LICENSE AGREEMENT</text>
        </element>
        ...
    </common_spine>

    <topical_analysis>Distribution agreement, streaming rights, revenue share...</topical_analysis>

    <specialized type="extraction">
        <extraction>
            <parties>...</parties>
            <defined_terms>...</defined_terms>
            <rights_grant>...</rights_grant>
            <financial_terms>...</financial_terms>
            ...
        </extraction>
    </specialized>

    <tags>
        <tag>distribution</tag>
        <tag>streaming</tag>
        ...
    </tags>
</response>
```

## Validation

```bash
python3 schemas/base/validate_mcs.py media_contracts_agents/extractor/extractor_format.xml
```

## Related Documentation

- [MCS Base Schema](../../schemas/base/README.md)
- [MCS Quick Start](../../schemas/base/QUICKSTART.md)
- [Implementation Matrix](../../schemas/base/IMPLEMENTATION_MATRIX.md)
