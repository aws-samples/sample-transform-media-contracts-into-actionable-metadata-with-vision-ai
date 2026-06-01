# Financial Analyst Agent

Specialist analyzer for financial term analysis, revenue waterfalls, and economic risk assessment.

## Purpose

Analyzes all financial terms and payment mechanics in media contracts, producing detailed analysis of:
- Revenue share structures and deduction waterfalls
- Minimum guarantees and recoupment terms
- Distribution fees and expense caps
- Payment mechanics and audit rights
- Blank fields and economic exposure

## MCS Implementation

**Type**: Specialist Analyzer
**Format File**: [financial_format.xml](financial_format.xml)
**MCS Parts**: 1 (Envelope), 2 (Metadata), 5 (Specialized), 6 (Findings), 7 (Tags)

### Part 5: Specialized Section

The `<specialized type="financial">` section contains:

- **Compensation Map**: Complete picture of all compensation flowing in the deal
- **Revenue Base Analysis**: Defined term, deduction layers, order of operations
- **Distribution Fee Analysis**: Fee percentage, base, waterfall position
- **Recoupable Expense Analysis**: Categories, caps, approval requirements
- **MG Analysis**: Amount, type, recoupment stream and rate, breakeven
- **Financial Waterfall**: Top-to-bottom revenue flow with formulas
- **MFN Analysis**: Most-favored-nations provisions and enforceability
- **Payment Mechanics**: Schedule, cash flow lag, currency, withholding, reserves
- **Audit Analysis**: Frequency, lookback period, cost allocation, enforceability
- **Residual/Royalty Analysis**: Guild residuals, contractual royalties
- **Financial Blank Fields**: Unfilled terms ranked by economic impact

### Part 6: Findings

The `<financial_findings>` section contains:

- **Risks**: Financial risks with severity levels and rationale
- **Ambiguities**: Terms that cannot be computed from contract language
- **Party Perspective**: Favorable and unfavorable terms for each party
- **Cross-References**: Issues flagged for other specialist agents

## Output Structure

```xml
<response analyzer="financial" schema_version="1.0" job_id="{ID}" timestamp="{ISO}">
    <metadata>
        <analyzer_name>financial</analyzer_name>
        <deal_structure_classification>MG_PLUS_OVERAGE</deal_structure_classification>
        <payor>Studio LLC</payor>
        <payee>Producer Inc</payee>
        <financial_finding_count>12</financial_finding_count>
        ...
    </metadata>

    <specialized type="financial">
        <compensation_map>...</compensation_map>
        <revenue_base_analysis>...</revenue_base_analysis>
        <financial_waterfall>...</financial_waterfall>
        <mg_analysis>...</mg_analysis>
        ...
    </specialized>

    <financial_findings>
        <risks>
            <risk>
                <description>Uncapped marketing expenses</description>
                <severity>HIGH</severity>
                <rationale>Studio can recoup unlimited marketing costs...</rationale>
            </risk>
        </risks>
        <ambiguities>...</ambiguities>
        <cross_references>...</cross_references>
    </financial_findings>

    <tags>
        <tag>revenue_share</tag>
        <tag>minimum_guarantee</tag>
        ...
    </tags>
</response>
```

## Key Analysis Features

### Waterfall Modeling
Constructs complete revenue waterfall from gross receipts down to net payment, identifying:
- Order of deductions
- Fee calculation bases
- Recoupment positions
- Breakeven thresholds

### Blank Field Analysis
Identifies unfilled financial terms and provides:
- Industry standard ranges
- Economic swing between low and high
- Impact on deal economics
- Ranked by dollar exposure

### Risk Assessment
Evaluates financial risks including:
- Uncapped expense exposure
- Ambiguous definition terms
- MFN compliance burden
- Audit enforceability gaps

## Consumed By

- **Risk Strategist**: Cross-cutting risk synthesis
- **Human Reviewers**: Content Finance VPs, Business Managers, Auditors

## Validation

```bash
python3 schemas/base/validate_mcs.py media_contracts_agents/financial/financial_format.xml
```

## Related Documentation

- [MCS Base Schema](../../schemas/base/README.md)
- [Financial Format XML](financial_format.xml)
