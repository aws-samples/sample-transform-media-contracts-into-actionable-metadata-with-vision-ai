# MCS Implementation Matrix

Quick reference for which MCS parts each analyzer should implement.

## Legend
- ✅ **REQUIRED** - Must be included
- 🟦 **OPTIONAL** - Include if relevant
- ❌ **NOT USED** - Don't include

## Analyzer Implementation Matrix

| Analyzer | Part 1<br/>Envelope | Part 2<br/>Metadata | Part 3<br/>Common Spine | Part 4<br/>Topical | Part 5<br/>Specialized | Part 6<br/>Findings | Part 7<br/>Tags |
|----------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **extractor** | ✅ | ✅ | ✅ | 🟦 | ✅ | ❌ | ✅ |
| **handwriting_analyzer** | ✅ | ✅ | ✅ | 🟦 | ✅ | 🟦 | ✅ |
| **financial** | ✅ | ✅ | ❌ | 🟦 | ✅ | ✅ | ✅ |
| **rights_clearance** | ✅ | ✅ | ❌ | 🟦 | ✅ | ✅ | ✅ |
| **regulatory_compliance** | ✅ | ✅ | ❌ | 🟦 | ✅ | ✅ | ✅ |
| **talent_guild_compliance** | ✅ | ✅ | ❌ | 🟦 | ✅ | ✅ | ✅ |
| **risk_strategist** | ✅ | ✅ | ❌ | 🟦 | ✅ | ✅ | ✅ |

## Part Descriptions

### Part 1: Envelope
```xml
<response analyzer="{ID}" schema_version="1.0" job_id="{ID}" timestamp="{ISO}">
```

### Part 2: Core Metadata
Standard metadata block with analyzer name, timestamp, source document, confidence level, and element counts.

### Part 3: Common Spine
Ordered text elements for document reconstruction. Required for analyzers that produce or transcribe text content.

**Use Cases:**
- **extractor**: Extracted contract text from OCR/parsing
- **handwriting_analyzer**: Transcribed handwritten regions

### Part 4: Topical Analysis
High-level topic summary. Include when the analyzer identifies thematic content.

### Part 5: Specialized Section
Domain-specific structure unique to each analyzer:
- **extractor**: `<extraction>` with contract components
- **financial**: Financial terms, waterfalls, MG analysis
- **rights_clearance**: Grant scope, territory, platform analysis
- **handwriting_analyzer**: Transcription elements, document assessment

### Part 6: Findings
Risk, gap, and ambiguity identification. Required for specialist analyzers that perform analysis (not raw extraction).

**Note:** Specialists typically extend with domain-specific findings sections:
- `<financial_findings>`
- `<rights_findings>`
- etc.

### Part 7: Tags
Topical categorization tags for search and correlation.

## Migration Path

For existing format files:

1. **Add MCS reference comment** at the top
2. **Verify envelope** includes all required attributes
3. **Ensure metadata** includes standard fields
4. **Add common_spine** if text is produced
5. **Standardize findings** structure if applicable
6. **Confirm tags** section exists

Example comment format:
```xml
<!-- Media Contracts Schema (MCS) v1.0
     Implements: Part 1 + Part 2 + Part 5 + Part 6 + Part 7
     See: schemas/base/mcs_base_schema.xml -->
```
