# Media Contracts Schema (MCS) v1.0

## Overview

The Media Contracts Schema (MCS) provides a standardized XML response format for all contract analysis agents in the system. It defines a modular structure where analyzers implement required core components and optional domain-specific sections.

## Schema Architecture

MCS is composed of 7 modular parts. Each analyzer includes relevant parts based on its function:

### Part 1: Envelope (REQUIRED - All Analyzers)
Root element with analyzer identification and job context.

### Part 2: Core Metadata (REQUIRED - All Analyzers)
Standard metadata including analyzer name, timestamp, source reference, and confidence.

### Part 3: Common Spine (OPTIONAL - Document Analyzers)
Ordered text elements for document reconstruction. Used by analyzers that produce or transcribe text content (extractor, handwriting_analyzer).

### Part 4: Topical Analysis (OPTIONAL)
High-level topic identification from analyzed content.

### Part 5: Specialized Section (REQUIRED - Analyzer-Specific)
Domain-specific analysis structure. Each analyzer defines its own schema within this section.

### Part 6: Findings (REQUIRED - Specialist Analyzers)
Standardized structure for risks, gaps, ambiguities, and cross-references. Not used by the extractor (which produces raw extraction, not analysis).

### Part 7: Tags (REQUIRED - All Analyzers)
Topical tags for categorization and search.

## Analyzer Types

### Document Analyzers
Produce text extraction or transcription:
- **extractor**: Initial contract extraction
- **handwriting_analyzer**: Handwriting transcription

**Required Parts**: 1, 2, 3, 7
**Optional Parts**: 4

### Specialist Analyzers
Perform domain-specific analysis on extracted content:
- **financial**: Financial term analysis
- **rights_clearance**: Rights and clearances analysis
- **regulatory_compliance**: Regulatory compliance review
- **talent_guild_compliance**: Guild/union compliance
- **risk_strategist**: Cross-cutting risk assessment

**Required Parts**: 1, 2, 5, 6, 7
**Optional Parts**: 4

## Schema Versioning

All responses must include `schema_version="1.0"` in the envelope. Version increments follow semantic versioning:
- **Major version**: Breaking changes to required fields
- **Minor version**: New optional fields or sections
- **Patch version**: Documentation or clarification only

## Implementation Guidelines

1. **Always include** envelope, core metadata, and tags
2. **Include common_spine** if your analyzer produces text content
3. **Include findings** if your analyzer performs risk/gap analysis
4. **Use standard element IDs** in common_spine: `elem_001`, `elem_002`, etc.
5. **Use standard confidence levels**: `high`, `medium`, `low`
6. **Use ISO 8601 timestamps**: `2024-03-21T14:30:00Z`

## Example Usage

See individual format files in `/media_contracts_agents/{analyzer}/` for complete implementation examples:
- `extractor_format.xml` - Document analyzer with common_spine
- `financial_format.xml` - Specialist analyzer with findings
- `handwriting_format.xml` - Hybrid analyzer with both common_spine and findings
