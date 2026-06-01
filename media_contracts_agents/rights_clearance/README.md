# Rights & Clearances Analyst Agent

Specialist analyzer for rights grants, territorial scope, clearance status, and chain of title.

## Purpose

Analyzes all rights and clearance provisions in media contracts, identifying:
- Rights granted vs. rights needed
- Territory and platform gaps
- Chain of title issues
- Music and embedded IP clearance status
- E&O insurability concerns

## MCS Implementation

**Type**: Specialist Analyzer
**Format File**: [rights_format.xml](rights_format.xml)
**MCS Parts**: 1 (Envelope), 2 (Metadata), 5 (Specialized), 6 (Findings), 7 (Tags)

### Part 5: Specialized Section

The `<specialized type="rights_clearance">` section contains:

- **Grant Scope Analysis**: Broad vs. narrow, specific rights granted, rights gaps, silent zone rights
- **Territory Analysis**: Territories granted, restrictions, gaps, language-territory alignment
- **Platform/Media Analysis**: Licensed media, restrictions, future-proofing, silent zone platforms
- **Language Rights Analysis**: Dubbing, subtitling, cost responsibility, quality approval, ownership
- **Chain of Title Analysis**: IP owner, warranty strength, work-for-hire status, prior encumbrances
- **Music Licensing Analysis**: Sync rights, master use, public performance (three-legged stool)
- **Embedded IP Analysis**: Clearance warranties, pending clearances, indemnification backing
- **Sublicensing/Assignment Analysis**: Permissions, approval mechanics, change of control triggers
- **Exclusivity/Holdback Analysis**: Exclusivity type, holdback provisions, gaps
- **Reversion Analysis**: Reversion triggers, sublicense survival, sell-off rights, materials return
- **E&O Insurability Assessment**: Likely insurable status, concerns for insurers
- **Digital/Emerging Rights Analysis**: AI training, NFT/metaverse, social media, digital likeness

### Part 6: Findings

The `<rights_findings>` section contains:

- **Rights Gaps**: Missing rights with severity, category, exploitation impact
- **Clearance Risks**: Clearance risks with mitigation strategies
- **Cross-References**: Issues flagged for other specialist agents

## Output Structure

```xml
<response analyzer="rights_clearance" schema_version="1.0" job_id="{ID}" timestamp="{ISO}">
    <metadata>
        <analyzer_name>rights_clearance</analyzer_name>
        <grantor>Content Owner LLC</grantor>
        <grantee>Distributor Inc</grantee>
        <overall_rights_posture>CONDITIONAL</overall_rights_posture>
        <rights_gap_count>5</rights_gap_count>
        <clearance_risk_count>3</clearance_risk_count>
        ...
    </metadata>

    <specialized type="rights_clearance">
        <grant_scope_analysis>
            <scope_classification>NARROW</scope_classification>
            <rights_granted>
                <right>Linear television broadcast</right>
                <right>Subscription video-on-demand</right>
            </rights_granted>
            <rights_not_granted_but_likely_needed>
                <gap>
                    <right>FAST channel distribution</right>
                    <why_needed>Grantee's business model includes FAST</why_needed>
                </gap>
            </rights_not_granted_but_likely_needed>
            <silent_zone_rights>
                <item>
                    <right>AI training on content</right>
                    <significance>HIGH</significance>
                    <note>Contract predates AI training concerns</note>
                </item>
            </silent_zone_rights>
        </grant_scope_analysis>

        <territory_analysis>...</territory_analysis>
        <music_licensing_analysis>...</music_licensing_analysis>
        <eo_insurability_assessment>
            <likely_insurable>YES_WITH_CONDITIONS</likely_insurable>
            <concerns>
                <concern>Pending music clearances for 3 tracks</concern>
                <concern>No work-for-hire documentation for archival footage</concern>
            </concerns>
        </eo_insurability_assessment>
        ...
    </specialized>

    <rights_findings>
        <rights_gaps>
            <gap>
                <description>FAST channel rights not granted</description>
                <severity>HIGH</severity>
                <category>MEDIA</category>
                <exploitation_impact>Cannot distribute via planned FAST channels</exploitation_impact>
            </gap>
        </rights_gaps>
        <clearance_risks>
            <risk>
                <description>Music sync rights pending</description>
                <severity>MEDIUM</severity>
                <mitigation>Obtain clearances pre-launch or replace tracks</mitigation>
            </risk>
        </clearance_risks>
        <cross_references>
            <cross_reference agent="financial" note="Revenue projections assume FAST distribution"/>
        </cross_references>
    </rights_findings>

    <tags>
        <tag>rights_gaps</tag>
        <tag>music_clearance</tag>
        <tag>territory_restrictions</tag>
    </tags>
</response>
```

## Key Analysis Features

### Silent Zone Identification
Identifies rights neither granted nor explicitly reserved:
- Emerging technologies (AI, NFT, metaverse)
- Platform ambiguities (e.g., FAST channels in older contracts)
- Language rights not addressed

### Three-Legged Music Clearance
Verifies all three required music rights:
1. **Sync Rights**: Right to use composition in timed synchronization
2. **Master Use**: Right to use specific recording
3. **Public Performance**: PRO clearance (ASCAP, BMI, SESAC, GMR)

### E&O Insurability
Assesses factors that affect errors & omissions insurance:
- Chain of title gaps
- Clearance warranty strength
- Pending clearances
- Third-party IP exposure

### Territory-Language Alignment
Checks that language rights cover all granted territories:
- Dubbing/subtitling rights for each territory
- Cost responsibility clarity
- Ownership of localized versions

## Consumed By

- **Risk Strategist**: Cross-cutting risk synthesis
- **Human Reviewers**: R&C Directors, Production Counsel, E&O Brokers, Music Supervisors

## Validation

```bash
python3 schemas/base/validate_mcs.py media_contracts_agents/rights_clearance/rights_format.xml
```

## Related Documentation

- [MCS Base Schema](../../schemas/base/README.md)
- [Rights Format XML](rights_format.xml)
