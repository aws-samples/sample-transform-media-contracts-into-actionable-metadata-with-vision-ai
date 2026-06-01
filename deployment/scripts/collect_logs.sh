#!/bin/bash
set -euo pipefail

# ── Collect all MediaContracts logs into a single file ─────────────────────
#
# Usage:
#   DEPLOYMENT_ID=mc ./deployment/scripts/collect_logs.sh
#   DEPLOYMENT_ID=mc ./deployment/scripts/collect_logs.sh --minutes 30
#   DEPLOYMENT_ID=mc ./deployment/scripts/collect_logs.sh --job-id abc-123
#
# Output: logs/collected-{timestamp}.txt

REGION="${AWS_REGION:-us-west-2}"
DEPLOYMENT_ID="${DEPLOYMENT_ID:?DEPLOYMENT_ID required}"
MINUTES="${MINUTES:-15}"
JOB_ID=""

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --minutes) MINUTES="$2"; shift 2 ;;
        --job-id)  JOB_ID="$2"; shift 2 ;;
        *)         echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# Calculate start time
if [[ "$(uname)" == "Darwin" ]]; then
    START_MS=$(( $(date -v-${MINUTES}M +%s) * 1000 ))
else
    START_MS=$(( $(date -d "${MINUTES} minutes ago" +%s) * 1000 ))
fi

mkdir -p logs
OUTFILE="logs/collected-$(date +%Y%m%dT%H%M%S).txt"

echo "═══════════════════════════════════════════════════════════" > "$OUTFILE"
echo "  MediaContracts Log Collection" >> "$OUTFILE"
echo "  Deployment: ${DEPLOYMENT_ID}" >> "$OUTFILE"
echo "  Region:     ${REGION}" >> "$OUTFILE"
echo "  Lookback:   ${MINUTES} minutes" >> "$OUTFILE"
echo "  Job filter: ${JOB_ID:-none}" >> "$OUTFILE"
echo "  Collected:  $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$OUTFILE"
echo "═══════════════════════════════════════════════════════════" >> "$OUTFILE"
echo "" >> "$OUTFILE"

# Log groups to check
LOG_GROUPS=(
    "/aws/bedrock-agentcore/runtimes/media-contracts-orchestrator-${DEPLOYMENT_ID}"
    "/aws/lambda/media-contracts-specialist-financial-${DEPLOYMENT_ID}"
    "/aws/lambda/media-contracts-specialist-rights-clearance-${DEPLOYMENT_ID}"
    "/aws/lambda/media-contracts-specialist-talent-guild-compliance-${DEPLOYMENT_ID}"
    "/aws/lambda/media-contracts-specialist-regulatory-compliance-${DEPLOYMENT_ID}"
    "/aws/lambda/media-contracts-specialist-risk-strategist-${DEPLOYMENT_ID}"
    "/aws/lambda/media-contracts-specialist-handwriting-analyzer-${DEPLOYMENT_ID}"
    "/aws/lambda/media-contracts-auto-trigger-${DEPLOYMENT_ID}"
    "/aws/lambda/media-contracts-kb-sync-contract-${DEPLOYMENT_ID}"
    "/aws/lambda/media-contracts-kb-sync-terms-${DEPLOYMENT_ID}"
    "/aws/lambda/media-contracts-gw-observability-${DEPLOYMENT_ID}"
)

# Find actual log group names (they have the stack suffix appended)
echo "Discovering log groups..." >&2

FOUND_GROUPS=()
for prefix in "${LOG_GROUPS[@]}"; do
    while IFS= read -r group; do
        [[ -n "$group" ]] && FOUND_GROUPS+=("$group")
    done < <(aws logs describe-log-groups \
        --log-group-name-prefix "$prefix" \
        --region "$REGION" \
        --query "logGroups[].logGroupName" \
        --output text 2>/dev/null | tr '\t' '\n')
done

# Also check for the orchestrator app logs (different prefix pattern)
while IFS= read -r group; do
    [[ -n "$group" ]] && FOUND_GROUPS+=("$group")
done < <(aws logs describe-log-groups \
    --log-group-name-prefix "/aws/bedrock-agentcore/runtimes/media-contracts-orchestrator-${DEPLOYMENT_ID}" \
    --region "$REGION" \
    --query "logGroups[].logGroupName" \
    --output text 2>/dev/null | tr '\t' '\n')

# Deduplicate
FOUND_GROUPS=($(printf '%s\n' "${FOUND_GROUPS[@]}" | sort -u))

echo "Found ${#FOUND_GROUPS[@]} log groups" >&2

for group in "${FOUND_GROUPS[@]}"; do
    echo "" >> "$OUTFILE"
    echo "───────────────────────────────────────────────────────────" >> "$OUTFILE"
    echo "  LOG GROUP: ${group}" >> "$OUTFILE"
    echo "───────────────────────────────────────────────────────────" >> "$OUTFILE"
    echo "" >> "$OUTFILE"

    # Build filter pattern
    FILTER=""
    if [[ -n "$JOB_ID" ]]; then
        FILTER="\"${JOB_ID}\""
    fi

    # Get recent log events
    if [[ -n "$FILTER" ]]; then
        aws logs filter-log-events \
            --log-group-name "$group" \
            --region "$REGION" \
            --start-time "$START_MS" \
            --filter-pattern "$FILTER" \
            --query "events[].message" \
            --output text 2>/dev/null >> "$OUTFILE" || echo "  (no events or access denied)" >> "$OUTFILE"
    else
        aws logs filter-log-events \
            --log-group-name "$group" \
            --region "$REGION" \
            --start-time "$START_MS" \
            --query "events[].message" \
            --output text 2>/dev/null >> "$OUTFILE" || echo "  (no events or access denied)" >> "$OUTFILE"
    fi
done

echo "" >> "$OUTFILE"
echo "═══════════════════════════════════════════════════════════" >> "$OUTFILE"
echo "  END OF LOG COLLECTION" >> "$OUTFILE"
echo "═══════════════════════════════════════════════════════════" >> "$OUTFILE"

LINES=$(wc -l < "$OUTFILE" | tr -d ' ')
echo "" >&2
echo "Done. ${LINES} lines written to: ${OUTFILE}" >&2
