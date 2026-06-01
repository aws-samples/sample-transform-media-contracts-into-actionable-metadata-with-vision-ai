# Risk Strategist Agent

Cross-cutting risk synthesis and negotiation strategy advisor.

## Purpose

Synthesizes findings from all specialist agents to produce:
- Unified risk assessment across all domains
- Deal-killer identification
- Negotiation priorities ranked by business impact
- Party-specific negotiation posture recommendations
- Executive summary for non-lawyer stakeholders

## MCS Implementation

**Type**: Specialist Analyzer (Findings Embedded)
**Format File**: [risk_format.xml](risk_format.xml)
**MCS Parts**: 1 (Envelope), 2 (Metadata), 5 (Specialized), 7 (Tags)

**Note**: Risk strategist **embeds findings within the specialized section** rather than using a separate Part 6 findings section.

### Part 5: Specialized Section

The `<specialized type="risk_strategy">` section contains:

- **Integrated Risk Map**: Cross-cutting risks synthesized from all specialists
  - Financial risks
  - Rights risks
  - Regulatory risks
  - Guild/talent risks
  - Risk interactions and compounding factors

- **Deal-Killer Assessment**: Contract-breaking issues that could derail the deal
  - Severity classification
  - Resolution difficulty
  - Timeline to resolution
  - Dealbreaker vs. material issue vs. negotiable point

- **Negotiation Priorities**: Ranked list of terms to negotiate
  - Business impact score
  - Leverage assessment
  - Fallback positions
  - Walk-away criteria

- **Party-Specific Strategy**: Tailored recommendations for each party
  - Favorable terms to preserve
  - Unfavorable terms to challenge
  - Market leverage assessment
  - Negotiation posture (aggressive, collaborative, defensive)

- **Executive Summary**: Plain-language summary for non-lawyers
  - Deal characterization
  - Major risks in business terms
  - Key financial exposure
  - Go/no-go recommendation with conditions

## Output Structure

```xml
<response analyzer="risk_strategist" schema_version="1.0" job_id="{ID}" timestamp="{ISO}">
    <metadata>
        <analyzer_name>risk_strategist</analyzer_name>
        <contract_classification>High-complexity distribution deal</contract_classification>
        <overall_risk_rating>MEDIUM-HIGH</overall_risk_rating>
        <deal_killer_count>0</deal_killer_count>
        <material_risk_count>3</material_risk_count>
        <negotiation_priority_count>8</negotiation_priority_count>
        ...
    </metadata>

    <specialized type="risk_strategy">
        <integrated_risk_map>
            <risk_category category="financial">
                <risk>
                    <description>Uncapped marketing expense recoupment</description>
                    <severity>HIGH</severity>
                    <source_agents>financial</source_agents>
                    <business_impact>
                        Distributor can recoup unlimited marketing costs before owner
                        sees revenue. Breakeven point unknowable. Potential zero payout.
                    </business_impact>
                    <interacts_with>
                        <interaction risk_id="audit_gap">
                            Audit rights weak. Cannot verify marketing spend reasonableness.
                        </interaction>
                    </interacts_with>
                </risk>
            </risk_category>

            <risk_category category="rights">
                <risk>
                    <description>FAST channel rights missing</description>
                    <severity>HIGH</severity>
                    <source_agents>rights_clearance</source_agents>
                    <business_impact>
                        Grantee's business plan assumes FAST distribution. Rights gap
                        prevents 30% of projected revenue. Deal economics collapse.
                    </business_impact>
                    <interacts_with>
                        <interaction risk_id="revenue_projections">
                            Financial analysis assumes FAST revenue. Not achievable.
                        </interaction>
                    </interacts_with>
                </risk>
            </risk_category>

            <risk_category category="regulatory">...</risk_category>
            <risk_category category="talent_guild">...</risk_category>

            <compounding_factors>
                <factor>
                    Marketing expense + audit weakness + FAST rights gap = deal economics
                    fundamentally unsound for grantee. Owner has all leverage.
                </factor>
            </compounding_factors>
        </integrated_risk_map>

        <deal_killer_assessment>
            <deal_killer_threshold>
                Contract-breaking issues that make deal non-executable or commercially
                unviable without resolution.
            </deal_killer_threshold>
            <deal_killers>
                <!-- No deal-killers identified in this contract -->
            </deal_killers>
            <material_issues>
                <issue>
                    <description>Missing FAST rights + uncapped expenses</description>
                    <severity>MATERIAL</severity>
                    <resolution_difficulty>MEDIUM</resolution_difficulty>
                    <timeline_to_resolution>2-4 weeks of negotiation</timeline_to_resolution>
                    <status>NEGOTIABLE</status>
                    <fallback>
                        Add FAST rights + cap marketing at 25% of gross. If refused,
                        re-run financial model with conservative assumptions.
                    </fallback>
                </issue>
            </material_issues>
        </deal_killer_assessment>

        <negotiation_priorities>
            <priority rank="1">
                <term>Grant FAST channel rights</term>
                <business_impact_score>9/10</business_impact_score>
                <leverage_assessment>MEDIUM - owner may not understand FAST value yet</leverage_assessment>
                <negotiation_strategy>
                    Frame as extending existing SVOD grant to include FAST. Industry
                    standard. Enables wider distribution. Minimal risk to owner.
                </negotiation_strategy>
                <fallback_position>
                    Accept with lower revenue share for FAST tier (e.g., 10% vs. 15%).
                </fallback_position>
            </priority>

            <priority rank="2">
                <term>Cap marketing expense recoupment</term>
                <business_impact_score>8/10</business_impact_score>
                <leverage_assessment>LOW - standard distributor request, owner will resist</leverage_assessment>
                <negotiation_strategy>
                    Propose reasonable cap (e.g., 25% of gross or $X per title). Show
                    industry comps. Emphasize audit burden if uncapped.
                </negotiation_strategy>
                <fallback_position>
                    Accept uncapped but negotiate approval rights above $X threshold.
                </fallback_position>
            </priority>

            <!-- Priorities 3-8... -->
        </negotiation_priorities>

        <party_specific_strategy party="Grantee (Distributor Inc)">
            <posture>COLLABORATIVE with pressure points</posture>
            <favorable_terms_to_preserve>
                <term>Exclusive territory grant (all markets)</term>
                <term>15-year term with automatic renewal</term>
                <term>Sublicensing rights without approval</term>
            </favorable_terms_to_preserve>
            <unfavorable_terms_to_challenge>
                <term>Uncapped marketing expense recoupment (Priority #2)</term>
                <term>Missing FAST rights (Priority #1)</term>
                <term>Weak audit rights (Priority #5)</term>
            </unfavorable_terms_to_challenge>
            <leverage_factors>
                <factor>Owner needs capital. Motivated to close.</factor>
                <factor>Distributor has FAST infrastructure owner lacks.</factor>
                <factor>No competing offers disclosed.</factor>
            </leverage_factors>
            <walk_away_criteria>
                If owner refuses FAST rights AND caps on marketing, deal becomes
                non-viable. Revenue projections require both.
            </walk_away_criteria>
        </party_specific_strategy>

        <party_specific_strategy party="Grantor (Content Owner LLC)">
            <posture>PRESERVE FLEXIBILITY</posture>
            <!-- Owner's perspective... -->
        </party_specific_strategy>

        <executive_summary>
            <deal_characterization>
                15-year worldwide distribution deal for catalog library. Revenue share
                structure with MG. Distributor has broad rights but missing key platforms.
            </deal_characterization>

            <major_risks_business_terms>
                1. Missing FAST channel rights prevent 30% of projected revenue
                2. Uncapped marketing expenses could eliminate all payout to owner
                3. Weak audit rights make expense verification difficult
                4. SAG-AFTRA digital likeness provisions need 2023 updates
            </major_risks_business_terms>

            <key_financial_exposure>
                Owner: Revenue may be $0 despite successful distribution (expense recoupment)
                Distributor: Cannot execute FAST strategy without additional rights
            </key_financial_exposure>

            <go_no_go_recommendation>
                <recommendation>PROCEED WITH RENEGOTIATION</recommendation>
                <conditions>
                    Must resolve: FAST rights, marketing cap, audit strengthening.
                    Nice to have: SAG-AFTRA updates, GDPR provisions.
                    Timeline: 2-4 weeks of negotiation expected.
                </conditions>
            </go_no_go_recommendation>
        </executive_summary>
    </specialized>

    <tags>
        <tag>high_priority_negotiation</tag>
        <tag>material_risks</tag>
        <tag>fast_rights_gap</tag>
    </tags>
</response>
```

## Key Analysis Features

### Cross-Specialist Synthesis
Integrates findings from all specialists:
- Financial (revenue, expenses, waterfalls)
- Rights & Clearances (grants, gaps, chain of title)
- Regulatory (compliance obligations, costs)
- Talent & Guild (residuals, consents, credits)

### Risk Interaction Analysis
Identifies how risks compound:
- Missing rights + optimistic financials = unachievable projections
- Weak warranties + E&O concerns = insurance denial
- Uncapped expenses + weak audits = unverifiable exposure

### Business Impact Scoring
Translates legal issues into business impact:
- Revenue at risk (dollars or percentage)
- Timeline to resolution
- Probability of issue materializing
- Relationship damage potential

### Negotiation Playbook
Provides actionable negotiation guidance:
- Priorities ranked by business impact
- Leverage assessment for each term
- Specific negotiation strategies
- Fallback positions
- Walk-away criteria

## Consumed By

- **Human Reviewers**: Business Affairs Executives, Content Acquisition VPs, Legal Counsel, Deal Makers

## Unique MCS Pattern

Unlike other specialists, risk strategist **embeds findings within specialized section** because its analysis IS the synthesis of all findings. No separate findings section needed.

## Validation

```bash
python3 schemas/base/validate_mcs.py media_contracts_agents/risk_strategist/risk_format.xml
```

## Related Documentation

- [MCS Base Schema](../../schemas/base/README.md)
- [Risk Format XML](risk_format.xml)
