# Handwriting Analyzer Agent

Hybrid document analyzer that transcribes handwritten annotations, amendments, and signatures.

## Purpose

Analyzes contracts with handwritten elements, producing:
- Accurate transcriptions of handwritten text
- Confidence levels for each region
- Morphological analysis of writing characteristics
- Assessment of document legibility and completeness

## MCS Implementation

**Type**: Hybrid Analyzer (Document + Analysis)
**Format File**: [handwriting_format.xml](handwriting_format.xml)
**MCS Parts**: 1 (Envelope), 2 (Metadata), 3 (Common Spine), 4 (Topical Analysis), 5 (Specialized), 7 (Tags)

### Part 3: Common Spine

**CRITICAL**: For pages analyzed only by the handwriting analyzer (no printed text extraction), the common_spine **IS** the text source for correlation and downstream consumers.

Each transcribed handwritten region becomes a spine element:
- Unique ID (`elem_001`, `elem_002`, etc.)
- Structural tag (P for main text, Note for marginal annotations, H1/H2 for identifiable headings)
- Order in reading sequence
- Page reference

Every transcribed word **must** appear in the spine.

### Part 5: Specialized Section

The `<specialized type="handwriting">` section contains:

- **Elements**: One per handwritten text region
  - Type (handwritten_text, marginal_annotation)
  - Location description
  - Handwriting style (cursive, print, mixed)
  - Transcription with confidence markers
  - Structured line-by-line text
  - Uncertain elements and illegible sections
  - Morphological characteristics
  - Physical evidence (ink type, paper condition)

- **Document Assessment**:
  - Overall legibility
  - Transcription completeness percentage
  - Primary challenges
  - Recommended follow-up

### No Findings Section

Handwriting analyzer is a **hybrid** that produces transcription (not analysis), so it does not include a findings section (Part 6). The transcribed content flows into the common_spine for downstream analysis.

## Output Structure

```xml
<response analyzer="handwriting_analyzer" schema_version="1.0"
         job_id="{ID}" timestamp="{ISO}" page="{N}">
    <metadata>
        <analyzer_name>handwriting_analyzer</analyzer_name>
        <source_image>s3://bucket/job/page_5.jpg</source_image>
        <element_count>3</element_count>
        <confidence>medium</confidence>
        ...
    </metadata>

    <common_spine element_count="3">
        <element id="elem_001" tag="P" order="1" page="5">
            <text>Original text with handwritten amendment: "Net Revenue"</text>
        </element>
        <element id="elem_002" tag="Note" order="2" page="5">
            <text>Initialed: JK 3/15/24</text>
        </element>
    </common_spine>

    <topical_analysis>Revenue definition amendment, initial approval</topical_analysis>

    <specialized type="handwriting">
        <elements>
            <element type="handwritten_text" id="region_001">
                <type>Handwritten Text</type>
                <summary>
                    <location>Top margin, crossed out "Gross" replaced with "Net"</location>
                    <handwriting_style>PRINT</handwriting_style>
                    <confidence_level>HIGH</confidence_level>
                </summary>
                <content>
                    <transcription>
                        <raw_text>"Net Revenue"</raw_text>
                        <structured_text>
                            <line number="1">Net Revenue</line>
                        </structured_text>
                    </transcription>
                    <analysis_notes>
                        <morphological_characteristics>Clear block letters, consistent pressure</morphological_characteristics>
                        <writer_identification>SINGLE_WRITER</writer_identification>
                    </analysis_notes>
                </content>
            </element>
            <element type="marginal_annotation" id="annot_001">
                <type>Marginal Annotation</type>
                <content>
                    <location>Bottom right corner</location>
                    <transcription>JK 3/15/24</transcription>
                    <confidence>HIGH</confidence>
                    <relationship_to_main_text>Initial approval of amendment</relationship_to_main_text>
                </content>
            </element>
        </elements>

        <document_assessment>
            <overall_legibility>GOOD</overall_legibility>
            <transcription_completeness>95%</transcription_completeness>
            <primary_challenges>Minor ink bleed-through on reverse</primary_challenges>
        </document_assessment>
    </specialized>

    <tags>
        <tag>amendment</tag>
        <tag>initials</tag>
    </tags>
</response>
```

## Key Features

### Confidence Tracking
Each transcribed element includes:
- Region-level confidence (HIGH, MEDIUM, LOW)
- Character/word-level uncertain elements
- Illegible section markers

### Morphological Analysis
Analyzes writing characteristics:
- Style (cursive, print, mixed, historical scripts)
- Writer identification (single, multiple, unknown)
- Historical period estimation (if applicable)
- Document type classification

### Physical Evidence
Records physical characteristics:
- Ink type (pen, pencil, quill, other)
- Paper condition (good, fair, poor, degraded)
- Corrections present
- Bleed-through

## Validation

```bash
python3 schemas/base/validate_mcs.py media_contracts_agents/handwriting_analyzer/handwriting_format.xml
```

## Related Documentation

- [MCS Base Schema](../../schemas/base/README.md)
- [Handwriting Format XML](handwriting_format.xml)
