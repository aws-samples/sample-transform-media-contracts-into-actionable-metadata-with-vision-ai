# Talent & Guild Compliance Analyst Agent

Specialist analyzer for guild/union compliance, talent obligations, and collective bargaining agreements.

## Purpose

Analyzes talent and guild compliance provisions, identifying:
- Guild/union affiliations and CBA requirements
- Residual obligations and calculation methods
- Credit requirements and remedy provisions
- Morals clauses and key person provisions
- Performer rights (consent, approval, digital likeness)

## MCS Implementation

**Type**: Specialist Analyzer
**Format File**: [talent_format.xml](talent_format.xml)
**MCS Parts**: 1 (Envelope), 2 (Metadata), 5 (Specialized), 6 (Findings), 7 (Tags)

### Part 5: Specialized Section

The `<specialized type="talent_guild_compliance">` section contains:

- **Guild Affiliation Analysis**: Which guilds apply, CBA references, jurisdiction-specific rules
- **Residual Obligations**: Calculation methods, payment triggers, foreign use rules, new media
- **Credit Requirements**: On-screen credits, paid advertising, size/placement, remedy for failure
- **Consent & Approval Rights**: Script approval, director approval, final cut, marketing materials
- **Performer Rights**: Digital likeness, AI usage, voice cloning, posthumous rights
- **Morals Clause Analysis**: Trigger events, termination rights, pay-or-play protection
- **Key Person Provisions**: Key talent identified, replacement rights, material element clauses
- **Profit Participation**: Net profit definitions, audit rights for participants
- **Work-for-Hire vs. Services**: Employee classification, copyright ownership, loan-out structures

### Part 6: Findings

The `<talent_findings>` section contains:

- **Guild Compliance Risks**: Missing or inadequate guild provisions
- **Talent Rights Gaps**: Unaddressed performer rights or consent requirements
- **Credit Provision Issues**: Ambiguous or insufficient credit terms
- **Cross-References**: Issues flagged for other specialist agents

## Output Structure

```xml
<response analyzer="talent_guild_compliance" schema_version="1.0" job_id="{ID}" timestamp="{ISO}">
    <metadata>
        <analyzer_name>talent_guild_compliance</analyzer_name>
        <primary_territory>United States</primary_territory>
        <guilds_identified>SAG-AFTRA, DGA, WGA</guilds_identified>
        <compliance_posture>PARTIALLY_COMPLIANT</compliance_posture>
        <talent_finding_count>6</talent_finding_count>
        ...
    </metadata>

    <specialized type="talent_guild_compliance">
        <guild_affiliation_analysis>
            <guild_coverage>
                <guild>
                    <name>SAG-AFTRA</name>
                    <applicable_agreement>2023 TV/Theatrical Agreement</applicable_agreement>
                    <jurisdiction>United States</jurisdiction>
                    <addressed_in_contract>YES</addressed_in_contract>
                    <section_reference>Section 12: Guild Compliance</section_reference>
                    <compliance_assessment>
                        Contract references SAG-AFTRA but does not specify which agreement.
                        Ambiguity regarding new media use under 2023 terms.
                    </compliance_assessment>
                </guild>
                <guild>
                    <name>DGA</name>
                    <applicable_agreement>2021 Basic Agreement</applicable_agreement>
                    <jurisdiction>United States</jurisdiction>
                    <addressed_in_contract>PARTIAL</addressed_in_contract>
                    <compliance_assessment>
                        Director credit addressed. Residuals not explicitly tied to DGA schedule.
                    </compliance_assessment>
                </guild>
            </guild_coverage>
        </guild_affiliation_analysis>

        <residual_obligations>
            <residual_calculation>
                <guild>SAG-AFTRA</guild>
                <trigger>Reuse in any medium beyond initial broadcast</trigger>
                <calculation_basis>As per SAG-AFTRA schedule</calculation_basis>
                <foreign_use_rules>NOT_ADDRESSED</foreign_use_rules>
                <new_media_residuals>NOT_ADDRESSED</new_media_residuals>
                <payment_responsibility>Producer</payment_responsibility>
                <addressed_adequately>PARTIAL</addressed_adequately>
                <gap_description>
                    New media residuals not addressed. 2023 SAG-AFTRA agreement requires
                    streaming bonuses based on views. Contract predates agreement.
                </gap_description>
            </residual_calculation>
        </residual_obligations>

        <performer_rights_analysis>
            <digital_likeness>
                <consent_required>YES</consent_required>
                <scope_of_use>NOT_SPECIFIED</scope_of_use>
                <ai_training_addressed>NO</ai_training_addressed>
                <deepfake_protection>NO</deepfake_protection>
                <posthumous_use>NOT_ADDRESSED</posthumous_use>
                <gap_severity>HIGH</gap_severity>
                <note>
                    2023 SAG-AFTRA agreement requires specific consent for digital replica use.
                    Contract has generic likeness clause but no AI/digital replica protections.
                </note>
            </digital_likeness>
            <voice_rights>
                <voice_cloning_addressed>NO</voice_cloning_addressed>
                <ai_voice_generation>NOT_ADDRESSED</ai_voice_generation>
                <gap_severity>HIGH</gap_severity>
            </voice_rights>
        </performer_rights_analysis>

        <credit_requirements>...</credit_requirements>
        <morals_clause_analysis>...</morals_clause_analysis>
        ...
    </specialized>

    <talent_findings>
        <guild_compliance_risks>
            <risk>
                <description>2023 SAG-AFTRA new media residuals not addressed</description>
                <severity>HIGH</severity>
                <guild>SAG-AFTRA</guild>
                <applicable_agreement>2023 TV/Theatrical Agreement</applicable_agreement>
                <enforcement_risk>Guild grievance, unfair labor practice claim</enforcement_risk>
                <mitigation>Amend to incorporate 2023 terms or negotiate carve-out</mitigation>
            </risk>
            <risk>
                <description>Digital likeness/AI usage not per 2023 SAG-AFTRA requirements</description>
                <severity>HIGH</severity>
                <guild>SAG-AFTRA</guild>
                <mitigation>Add specific AI consent provisions per 2023 agreement</mitigation>
            </risk>
        </guild_compliance_risks>

        <talent_rights_gaps>
            <gap>
                <description>No voice cloning or AI voice generation provisions</description>
                <severity>MEDIUM</severity>
                <affected_party>All performers</affected_party>
                <industry_standard>Explicit consent required per 2023 guild agreements</industry_standard>
            </gap>
        </talent_rights_gaps>

        <credit_provision_issues>
            <issue>
                <description>Paid advertising credit not specified</description>
                <severity>LOW</severity>
                <affected_party>Director</affected_party>
                <dga_requirement>Above-the-title credit on all paid ads</dga_requirement>
            </issue>
        </credit_provision_issues>

        <cross_references>
            <cross_reference agent="financial" note="Residual obligations affect revenue waterfall"/>
            <cross_reference agent="rights" note="Digital likeness consent affects exploitation rights"/>
        </cross_references>
    </talent_findings>

    <tags>
        <tag>sag_aftra</tag>
        <tag>digital_likeness</tag>
        <tag>residuals</tag>
    </tags>
</response>
```

## Key Analysis Features

### Guild Agreement Tracking
Monitors compliance with specific CBAs:
- SAG-AFTRA (2023 TV/Theatrical, 2023 Commercials, etc.)
- DGA (2021 Basic Agreement)
- WGA (2023 MBA)
- IATSE (various locals)
- AFM (musicians)

### 2023 Strike Outcomes
Specifically identifies gaps related to 2023 SAG-AFTRA and WGA agreements:
- AI/digital replica consent requirements
- Streaming residuals and view-based bonuses
- Transparency obligations (view counts, revenue data)
- AI training restrictions

### Residual Calculation Verification
Validates residual payment mechanics:
- Correct calculation basis per guild schedule
- Payment triggers properly defined
- Foreign use and new media addressed
- Responsibility clearly allocated

### Digital Likeness Analysis
Evaluates performer digital rights protection:
- AI-generated replica consent
- Voice cloning provisions
- Deepfake protections
- Posthumous use rights
- Training data exclusions

## Consumed By

- **Risk Strategist**: Cross-cutting risk synthesis
- **Human Reviewers**: Production Counsel, Guild Representatives, Business Affairs

## Validation

```bash
python3 schemas/base/validate_mcs.py media_contracts_agents/talent_guild_compliance/talent_format.xml
```

## Related Documentation

- [MCS Base Schema](../../schemas/base/README.md)
- [Talent Format XML](talent_format.xml)
