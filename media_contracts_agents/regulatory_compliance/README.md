# Regulatory & Compliance Analyst Agent

Specialist analyzer for regulatory obligations, content ratings, accessibility, and data protection.

## Purpose

Analyzes regulatory and compliance requirements across territories and platforms, identifying:
- Applicable regulatory frameworks by territory
- Content rating and classification obligations
- Accessibility requirements (captions, audio description)
- Local content quotas
- Data protection and privacy compliance
- Sanctions and export control issues

## MCS Implementation

**Type**: Specialist Analyzer
**Format File**: [regulatory_format.xml](regulatory_format.xml)
**MCS Parts**: 1 (Envelope), 2 (Metadata), 5 (Specialized), 6 (Findings), 7 (Tags)

### Part 5: Specialized Section

The `<specialized type="regulatory_compliance">` section contains:

- **Regulatory Applicability Map**: Which frameworks apply to which territories
- **Content Rating Analysis**: Rating requirements, classification obligations, territorial variations
- **Accessibility Compliance**: Captions, audio description, subtitle standards by territory
- **Local Content Quota Analysis**: Quota obligations, contribution requirements, enforcement
- **Platform Regulatory Requirements**: Platform-specific obligations (YouTube, Netflix, etc.)
- **Data Protection Compliance**: GDPR, CCPA, data localization, transfer mechanisms
- **Export Control & Sanctions**: Sanctioned territories, export control classifications
- **Advertising & Marketing Compliance**: Ad standards, child protection, prohibited content
- **Broadcast/Streaming Licensing**: Broadcast licenses, streaming permits, regulatory approvals

### Part 6: Findings

The `<regulatory_findings>` section contains:

- **Regulatory Gaps**: Unaddressed obligations with severity and territory
- **Compliance Risks**: Potential violations with mitigation strategies
- **Conflicting Requirements**: Contradictions between jurisdictions
- **Cross-References**: Issues flagged for other specialist agents

## Output Structure

```xml
<response analyzer="regulatory_compliance" schema_version="1.0" job_id="{ID}" timestamp="{ISO}">
    <metadata>
        <analyzer_name>regulatory_compliance</analyzer_name>
        <territories_granted>Worldwide</territories_granted>
        <platforms_granted>Linear TV, SVOD, FAST</platforms_granted>
        <overall_regulatory_posture>PARTIALLY_ADDRESSED</overall_regulatory_posture>
        <regulatory_gap_count>8</regulatory_gap_count>
        <high_severity_gap_count>2</high_severity_gap_count>
        ...
    </metadata>

    <specialized type="regulatory_compliance">
        <regulatory_applicability_map>
            <territory_regime>
                <territory>European Union</territory>
                <applicable_frameworks>
                    <framework>EU AVMS Directive</framework>
                    <framework>GDPR</framework>
                    <framework>EU Accessibility Act</framework>
                </applicable_frameworks>
            </territory_regime>
            <territory_regime>
                <territory>United Kingdom</territory>
                <applicable_frameworks>
                    <framework>Ofcom Broadcasting Code</framework>
                    <framework>UK GDPR</framework>
                    <framework>Communications Act 2003</framework>
                </applicable_frameworks>
            </territory_regime>
        </regulatory_applicability_map>

        <accessibility_compliance>
            <caption_requirements>
                <territory_requirement>
                    <territory>United States</territory>
                    <standard>FCC CVAA - 21 CFR Part 79</standard>
                    <threshold>All video programming</threshold>
                    <format>CEA-608/CEA-708</format>
                    <addressed_in_contract>NO</addressed_in_contract>
                </territory_requirement>
                <territory_requirement>
                    <territory>European Union</territory>
                    <standard>EU Accessibility Act - EAA 2025</standard>
                    <threshold>Public-facing streaming services</threshold>
                    <addressed_in_contract>NO</addressed_in_contract>
                </territory_requirement>
            </caption_requirements>
            <audio_description_requirements>...</audio_description_requirements>
            <cost_responsibility>NOT_ADDRESSED</cost_responsibility>
            <compliance_gap_analysis>
                No accessibility provisions in contract. EU/US obligations require closed captions.
                Estimated cost: $X per content hour. Responsibility allocation needed.
            </compliance_gap_analysis>
        </accessibility_compliance>

        <data_protection_compliance>...</data_protection_compliance>
        <local_content_quota_analysis>...</local_content_quota_analysis>
        ...
    </specialized>

    <regulatory_findings>
        <regulatory_gaps>
            <gap>
                <description>No accessibility provisions (captions/audio description)</description>
                <severity>HIGH</severity>
                <territory>EU, US, UK</territory>
                <applicable_framework>EU EAA, FCC CVAA, Ofcom Code</applicable_framework>
                <enforcement_risk>Fines up to €X, FCC penalties</enforcement_risk>
            </gap>
            <gap>
                <description>GDPR data processing agreement missing</description>
                <severity>HIGH</severity>
                <territory>European Union</territory>
                <applicable_framework>GDPR Article 28</applicable_framework>
                <enforcement_risk>Up to 4% global annual revenue</enforcement_risk>
            </gap>
        </regulatory_gaps>

        <compliance_risks>
            <risk>
                <description>Content rating not addressed for theatrical content</description>
                <severity>MEDIUM</severity>
                <territory>Worldwide</territory>
                <mitigation>Obtain ratings from MPA, BBFC, FSK, etc. pre-release</mitigation>
            </risk>
        </compliance_risks>

        <conflicting_requirements>
            <conflict>
                <description>EU data localization vs. US Patriot Act requirements</description>
                <territories>EU, US</territories>
                <resolution_strategy>Standard Contractual Clauses + data segregation</resolution_strategy>
            </conflict>
        </conflicting_requirements>

        <cross_references>
            <cross_reference agent="financial" note="Accessibility costs not budgeted"/>
            <cross_reference agent="rights" note="EU local content quota affects territory value"/>
        </cross_references>
    </regulatory_findings>

    <tags>
        <tag>accessibility</tag>
        <tag>gdpr</tag>
        <tag>content_rating</tag>
    </tags>
</response>
```

## Key Analysis Features

### Territory-Framework Mapping
Maps each granted territory to applicable regulatory frameworks:
- Broadcast regulations (FCC, Ofcom, CSA, etc.)
- Content rating systems (MPA, BBFC, FSK, etc.)
- Data protection (GDPR, CCPA, LGPD, etc.)
- Accessibility laws (ADA, EU EAA, etc.)

### Gap Severity Assessment
Classifies regulatory gaps by:
- **HIGH**: Legal compliance risk, potential fines
- **MEDIUM**: Operational burden, reputational risk
- **LOW**: Best practice gaps, minor requirements

### Cost Impact Analysis
Estimates compliance costs for unaddressed obligations:
- Accessibility (captioning, audio description)
- Content ratings (submission fees, edits)
- Data protection (infrastructure, audits)

## Consumed By

- **Risk Strategist**: Cross-cutting risk synthesis
- **Human Reviewers**: Regulatory Counsel, Compliance Officers, Content Operations Directors

## Validation

```bash
python3 schemas/base/validate_mcs.py media_contracts_agents/regulatory_compliance/regulatory_format.xml
```

## Related Documentation

- [MCS Base Schema](../../schemas/base/README.md)
- [Regulatory Format XML](regulatory_format.xml)
