#!/bin/bash
set -euo pipefail

# ── Error handler ──────────────────────────────────────────────────────────
trap 'echo ""; echo "✗ destroy.sh failed at line ${LINENO}: ${BASH_COMMAND}"; exit 1' ERR

# ── Colors ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

_ts() { date '+%Y-%m-%d %H:%M:%S'; }
log_info() { echo -e "${BLUE}[$(_ts)]${NC} $1"; }
log_success() { echo -e "${GREEN}[$(_ts) ✓]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[$(_ts) !]${NC} $1"; }
log_error() { echo -e "${RED}[$(_ts) ✗]${NC} $1"; }

# ── Media Contracts Analyzer — Full Teardown Script ────────────────────────
#
# Usage:
#   DEPLOYMENT_ID=mc ./destroy.sh
#
# What this does (in order):
#   1. Reads STACK_SUFFIX from .deploy-state/{DEPLOYMENT_ID}.json
#   2. Requires you to type the DEPLOYMENT_ID to confirm.
#   3. Empties all S3 buckets for this deployment (all versions + delete markers).
#   4. Runs `cdk destroy --all` across every stack for this deployment.
#   5. Schedules the KMS key for deletion (7-day waiting period).
#   6. Verifies the stacks are gone.
#
# Required:
#   DEPLOYMENT_ID   Identifier used when the stacks were deployed (e.g. mc, dev)
#
# Optional:
#   AWS_REGION      AWS region (default: us-west-2)
#   KMS_WAIT_DAYS   KMS key deletion waiting period, 7-30 (default: 7)
#   STACK_SUFFIX    Override suffix (default: read from state file)
# ───────────────────────────────────────────────────────────────────────────

AWS_REGION="${AWS_REGION:-us-west-2}"
KMS_WAIT_DAYS="${KMS_WAIT_DAYS:-7}"
VPC_CLEANUP_ONLY=false

if [ "${1:-}" = "--vpc-cleanup-only" ]; then
  VPC_CLEANUP_ONLY=true
fi

if [ -z "${DEPLOYMENT_ID:-}" ]; then
  echo "✗ DEPLOYMENT_ID is required (e.g. DEPLOYMENT_ID=mc ./destroy.sh)"
  exit 1
fi

# ── Read STACK_SUFFIX from state file ──────────────────────────────────────
STATE_FILE=".deploy-state/${DEPLOYMENT_ID}.json"
if [ -z "${STACK_SUFFIX:-}" ]; then
  if [ -f "${STATE_FILE}" ]; then
    STACK_SUFFIX=$(python3 -c "import json; d=json.load(open('${STATE_FILE}')); print(d.get('stack_suffix',''))")
  fi
  if [ -z "${STACK_SUFFIX:-}" ]; then
    echo "✗ STACK_SUFFIX not found in ${STATE_FILE} and not set as env var."
    echo "  Set it manually: STACK_SUFFIX=03f DEPLOYMENT_ID=mc ./destroy.sh"
    exit 1
  fi
fi

export DEPLOYMENT_ID STACK_SUFFIX

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Helper to build stack names: MC-{Name}-{suffix}
_sn() { echo "MC-$1-${STACK_SUFFIX}"; }

# Stack names in reverse dependency order (matches app.py construct IDs)
STACKS=(
  "$(_sn ECS)"
  "$(_sn Dashboard)"
  "$(_sn AnalysisKBSync)"
  "$(_sn AutoTrigger)"
  "$(_sn Runtimes)"
  "$(_sn XRay)"
  "$(_sn Gateway)"
  "$(_sn Specialists)"
  "$(_sn TermsKB)"
  "$(_sn AnalysisKB)"
  "$(_sn IAM)"
  "$(_sn ECR)"
  "$(_sn DynamoDB)"
  "$(_sn S3)"
  "$(_sn InferenceProfiles)"
  "$(_sn Cognito)"
  "$(_sn Vpc)"
)

# Deployment-specific resource names
DEPLOYMENT_PREFIX="media-contracts"
BUCKET_SUFFIX="${DEPLOYMENT_ID}-${STACK_SUFFIX}"
ECS_SERVICE_NAME="${DEPLOYMENT_PREFIX}-${DEPLOYMENT_ID}-${STACK_SUFFIX}"

echo "════════════════════════════════════════════════════════"
echo "  Media Contracts Analyzer — Teardown"
echo "  Account:       ${ACCOUNT_ID}"
echo "  Region:        ${AWS_REGION}"
echo "  Deployment ID: ${DEPLOYMENT_ID}"
echo "  Stack Suffix:  ${STACK_SUFFIX}"
echo "  KMS wait:      ${KMS_WAIT_DAYS} days"
echo "════════════════════════════════════════════════════════"

# ── VPC cleanup only mode ──────────────────────────────────────────────────
if [ "${VPC_CLEANUP_ONLY}" = true ]; then
  echo ""
  log_info "Running VPC ENI cleanup only (--vpc-cleanup-only)"
  echo ""

  VPC_ID=$(aws cloudformation describe-stacks \
    --stack-name "$(_sn Vpc)" \
    --region "${AWS_REGION}" \
    --query "Stacks[0].Outputs[?OutputKey=='VpcId'].OutputValue" \
    --output text 2>/dev/null || true)

  if [ -z "${VPC_ID}" ] || [ "${VPC_ID}" = "None" ]; then
    # Try finding VPC by tags if stack is already gone
    VPC_ID=$(aws ec2 describe-vpcs \
      --filters Name=tag:project,Values=media-contracts Name=tag:deployment_id,Values="${DEPLOYMENT_ID}" \
      --region "${AWS_REGION}" \
      --query "Vpcs[0].VpcId" --output text 2>/dev/null || true)
  fi

  if [ -z "${VPC_ID}" ] || [ "${VPC_ID}" = "None" ]; then
    log_error "No VPC found for deployment ${DEPLOYMENT_ID}"
    exit 1
  fi

  log_info "Found VPC: ${VPC_ID}"

  # Reuse the final ENI verification logic
  log_info "Checking for ENIs in VPC ${VPC_ID}..."

  ALL_ENIS=$(aws ec2 describe-network-interfaces \
    --filters Name=vpc-id,Values="${VPC_ID}" \
    --region "${AWS_REGION}" \
    --query "NetworkInterfaces[].{ID:NetworkInterfaceId,Type:InterfaceType,Desc:Description,Status:Status}" \
    --output text 2>/dev/null || true)

  if [ -z "${ALL_ENIS}" ] || [ "${ALL_ENIS}" = "None" ]; then
    log_success "No ENIs found in VPC — clean state"
    exit 0
  fi

  log_warn "Found ENIs in VPC:"
  echo "${ALL_ENIS}" | while IFS=$'\t' read -r eni_id eni_type eni_desc eni_status; do
    echo "      ${eni_id} [${eni_type}] - ${eni_desc} (${eni_status})"
  done

  log_info "Attempting ENI cleanup..."

  # Delete VPC interface endpoints first (they own ENIs)
  ENDPOINT_IDS=$(aws ec2 describe-vpc-endpoints \
    --filters Name=vpc-id,Values="${VPC_ID}" Name=vpc-endpoint-type,Values="Interface" \
    --region "${AWS_REGION}" \
    --query "VpcEndpoints[].VpcEndpointId" \
    --output text 2>/dev/null || true)

  if [ -n "${ENDPOINT_IDS}" ] && [ "${ENDPOINT_IDS}" != "None" ]; then
    for ep_id in ${ENDPOINT_IDS}; do
      aws ec2 delete-vpc-endpoints --vpc-endpoint-ids "${ep_id}" --region "${AWS_REGION}" 2>/dev/null || true
      log_info "Deleted VPC endpoint ${ep_id}"
    done
    for i in $(seq 1 12); do
      sleep 10
      ENDPOINT_ENIS=$(aws ec2 describe-network-interfaces \
        --filters Name=vpc-id,Values="${VPC_ID}" Name=interface-type,Values="vpc_endpoint" \
        --region "${AWS_REGION}" \
        --query "NetworkInterfaces[].NetworkInterfaceId" \
        --output text 2>/dev/null || true)
      if [ -z "${ENDPOINT_ENIS}" ] || [ "${ENDPOINT_ENIS}" = "None" ]; then
        log_success "VPC endpoint ENIs released"
        break
      fi
      echo "    $(_ts) — Waiting for VPC endpoint ENIs to release (${i}/12)"
    done
  fi

  # Force detach and delete remaining ENIs
  for i in $(seq 1 12); do
    REMAINING_ENIS=$(aws ec2 describe-network-interfaces \
      --filters Name=vpc-id,Values="${VPC_ID}" \
      --region "${AWS_REGION}" \
      --query "NetworkInterfaces[].[NetworkInterfaceId,Status,Attachment.AttachmentId]" \
      --output text 2>/dev/null || true)

    if [ -z "${REMAINING_ENIS}" ] || [ "${REMAINING_ENIS}" = "None" ]; then
      log_success "All ENIs cleaned up"
      break
    fi

    echo "${REMAINING_ENIS}" | while IFS=$'\t' read -r eni_id eni_status attachment_id; do
      if [ "${eni_status}" = "available" ]; then
        aws ec2 delete-network-interface --network-interface-id "${eni_id}" --region "${AWS_REGION}" 2>/dev/null && \
          log_info "Deleted available ENI ${eni_id}" || true
      elif [ -n "${attachment_id}" ] && [ "${attachment_id}" != "None" ]; then
        log_warn "Force detaching ENI ${eni_id}..."
        aws ec2 detach-network-interface --attachment-id "${attachment_id}" --force --region "${AWS_REGION}" 2>/dev/null || true
        sleep 2
        aws ec2 delete-network-interface --network-interface-id "${eni_id}" --region "${AWS_REGION}" 2>/dev/null && \
          log_info "Deleted ENI ${eni_id}" || true
      fi
    done

    sleep 5
  done

  # Final check
  FINAL_ENIS=$(aws ec2 describe-network-interfaces \
    --filters Name=vpc-id,Values="${VPC_ID}" \
    --region "${AWS_REGION}" \
    --query "NetworkInterfaces[].NetworkInterfaceId" \
    --output text 2>/dev/null || true)

  if [ -n "${FINAL_ENIS}" ] && [ "${FINAL_ENIS}" != "None" ]; then
    log_error "Unable to clean up all ENIs. Remaining: ${FINAL_ENIS}"
    exit 1
  else
    log_success "VPC ENI cleanup complete"
  fi
  exit 0
fi

# ── Full teardown continues below ─────────────────────────────────────────
echo ""
echo "This will permanently delete:"
echo "  - All ${#STACKS[@]} CloudFormation stacks above"
echo "  - All objects in the S3 buckets (config, source, results, terms, logs) and all versions"
echo "  - The KMS key (scheduled, ${KMS_WAIT_DAYS}-day waiting period)"
echo "  - Both ECR repositories (orchestrator + UI) and all images"
echo "  - The AgentCore runtime, gateway, and knowledge base"
echo "  - All DynamoDB tables and their data"
echo ""
echo "Type the DEPLOYMENT_ID to confirm destruction:"
read -r CONFIRM

if [ "${CONFIRM}" != "${DEPLOYMENT_ID}" ]; then
  echo "✗ Confirmation mismatch. Aborted."
  exit 1
fi

echo ""
echo "✓ Confirmation accepted. Starting teardown."
echo ""

# ── Sync Python deps so cdk runs ───────────────────────────────────────────
echo "→ Syncing Python dependencies..."
unset VIRTUAL_ENV
uv sync
export VIRTUAL_ENV="${PWD}/.venv"
export PATH="${PWD}/.venv/bin:${PATH}"
echo ""

# ── Empty S3 buckets ───────────────────────────────────────────────────────
empty_bucket() {
  local bucket_name="$1"
  local exists
  exists=$(aws s3api head-bucket --bucket "${bucket_name}" --region "${AWS_REGION}" 2>&1 || echo "MISSING")
  if echo "${exists}" | grep -q "MISSING\|Not Found\|NoSuchBucket\|404\|403"; then
    echo "  (bucket ${bucket_name} does not exist — skipping)"
    return
  fi

  echo "  → Emptying s3://${bucket_name} (all versions + delete markers)..."

  # Delete all current object versions
  aws s3api list-object-versions --bucket "${bucket_name}" --region "${AWS_REGION}" \
    --output json --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}}' 2>/dev/null \
    | jq -c '{Objects: (.Objects // [])} | select(.Objects | length > 0)' \
    | while read -r batch; do
        [ -z "${batch}" ] && continue
        aws s3api delete-objects --bucket "${bucket_name}" --region "${AWS_REGION}" \
          --delete "${batch}" --output text --no-cli-pager > /dev/null || true
      done

  # Delete all delete-markers
  aws s3api list-object-versions --bucket "${bucket_name}" --region "${AWS_REGION}" \
    --output json --query '{Objects: DeleteMarkers[].{Key:Key,VersionId:VersionId}}' 2>/dev/null \
    | jq -c '{Objects: (.Objects // [])} | select(.Objects | length > 0)' \
    | while read -r batch; do
        [ -z "${batch}" ] && continue
        aws s3api delete-objects --bucket "${bucket_name}" --region "${AWS_REGION}" \
          --delete "${batch}" --output text --no-cli-pager > /dev/null || true
      done

  # Belt-and-suspenders: also run recursive rm in case of unversioned objects
  aws s3 rm "s3://${bucket_name}" --recursive --region "${AWS_REGION}" --only-show-errors || true

  echo "    ✓ ${bucket_name} emptied"
}

echo "── Emptying S3 buckets ───────────────────────────────────"
empty_bucket "${DEPLOYMENT_PREFIX}-config-${BUCKET_SUFFIX}"
empty_bucket "${DEPLOYMENT_PREFIX}-source-${BUCKET_SUFFIX}"
empty_bucket "${DEPLOYMENT_PREFIX}-results-${BUCKET_SUFFIX}"
empty_bucket "${DEPLOYMENT_PREFIX}-terms-${BUCKET_SUFFIX}"
empty_bucket "${DEPLOYMENT_PREFIX}-access-logs-${BUCKET_SUFFIX}"
echo ""

# ── Capture the KMS key ID before stacks are deleted ──────────────────────
echo "── Capturing KMS key ID from S3 stack ────────────────────"
KMS_KEY_ARN=""
KMS_KEY_ARN=$(aws cloudformation describe-stacks \
  --stack-name "$(_sn S3)" \
  --region "${AWS_REGION}" \
  --query "Stacks[0].Outputs[?OutputKey=='KmsKeyArn'].OutputValue" \
  --output text 2>/dev/null || true)

if [ -z "${KMS_KEY_ARN}" ] || [ "${KMS_KEY_ARN}" = "None" ]; then
  echo "  ⚠️  Could not read KmsKeyArn output from $(_sn S3) — "
  echo "      KMS key (if it exists) will not be scheduled for deletion by this script."
  KMS_KEY_ARN=""
else
  echo "  ✓ KMS key: ${KMS_KEY_ARN}"
fi
echo ""

# ── Capture VPC ID for ENI cleanup ─────────────────────────────────────────
VPC_ID=$(aws cloudformation describe-stacks \
  --stack-name "$(_sn Vpc)" \
  --region "${AWS_REGION}" \
  --query "Stacks[0].Outputs[?OutputKey=='VpcId'].OutputValue" \
  --output text 2>/dev/null || true)

# ── Delete ECS Express service (releases ENIs before VPC teardown) ──────────
echo "── Deleting ECS Express service ──────────────────────────"
ECS_SERVICE_ARN=$(aws ecs list-services \
  --cluster default \
  --region "${AWS_REGION}" \
  --query "serviceArns[?contains(@, '${ECS_SERVICE_NAME}')] | [0]" \
  --output text 2>/dev/null || true)

if [ -n "${ECS_SERVICE_ARN}" ] && [ "${ECS_SERVICE_ARN}" != "None" ]; then
  echo "  → Deleting service ${ECS_SERVICE_NAME}..."
  aws ecs delete-service \
    --cluster default \
    --service "${ECS_SERVICE_ARN}" \
    --force \
    --region "${AWS_REGION}" \
    --no-cli-pager > /dev/null

  # Wait for ECS to drain tasks and release ENIs (up to 5 minutes)
  echo "  → Waiting for service deletion and ENI release..."
  for i in $(seq 1 30); do
    REMAINING=$(aws ecs describe-services \
      --cluster default \
      --services "${ECS_SERVICE_ARN}" \
      --region "${AWS_REGION}" \
      --query "services[0].status" \
      --output text 2>/dev/null || echo "GONE")
    if [ "${REMAINING}" = "INACTIVE" ] || [ "${REMAINING}" = "GONE" ] || [ "${REMAINING}" = "None" ]; then
      echo "    ✓ Service deleted"
      break
    fi
    echo "    $(date '+%H:%M:%S') — status: ${REMAINING} (${i}/30)"
    sleep 10
  done

  # Extra wait for ENI release — ECS can take several minutes after service goes INACTIVE
  echo "  → Waiting for ENIs to release from VPC subnets..."

  if [ -n "${VPC_ID}" ] && [ "${VPC_ID}" != "None" ]; then
    for i in $(seq 1 36); do
      ENI_IDS=$(aws ec2 describe-network-interfaces \
        --filters \
          Name=vpc-id,Values="${VPC_ID}" \
          Name=group-name,Values="media-contracts-ui-task-sg-${DEPLOYMENT_ID}-${STACK_SUFFIX}" \
        --region "${AWS_REGION}" \
        --query "NetworkInterfaces[].NetworkInterfaceId" \
        --output text 2>/dev/null || true)

      if [ -z "${ENI_IDS}" ] || [ "${ENI_IDS}" = "None" ]; then
        echo "    ✓ All ECS ENIs released"
        break
      fi

      # Try deleting any that are now available
      for eni_id in ${ENI_IDS}; do
        ENI_STATUS=$(aws ec2 describe-network-interfaces \
          --network-interface-ids "${eni_id}" \
          --region "${AWS_REGION}" \
          --query "NetworkInterfaces[0].Status" \
          --output text 2>/dev/null || echo "gone")
        if [ "${ENI_STATUS}" = "available" ]; then
          aws ec2 delete-network-interface --network-interface-id "${eni_id}" --region "${AWS_REGION}" 2>/dev/null || true
          echo "    ✓ Deleted ${eni_id}"
        fi
      done

      # If we've waited 5+ minutes and ENIs are still attached, try forced detachment
      if [ $i -ge 30 ] && [ -n "${ENI_IDS}" ]; then
        echo "    ⚠️  ENIs still attached after 5 minutes, attempting forced detachment..."
        for eni_id in ${ENI_IDS}; do
          ATTACHMENT_ID=$(aws ec2 describe-network-interfaces \
            --network-interface-ids "${eni_id}" \
            --region "${AWS_REGION}" \
            --query "NetworkInterfaces[0].Attachment.AttachmentId" \
            --output text 2>/dev/null || echo "")
          if [ -n "${ATTACHMENT_ID}" ] && [ "${ATTACHMENT_ID}" != "None" ]; then
            aws ec2 detach-network-interface \
              --attachment-id "${ATTACHMENT_ID}" \
              --force \
              --region "${AWS_REGION}" 2>/dev/null || true
            echo "    ⚠️  Force detached ${eni_id}"
          fi
        done
      fi

      echo "    $(date '+%H:%M:%S') — ENIs still attached (${i}/36, waiting 10s)"
      sleep 10
    done
  fi
else
  echo "  (no ECS Express service found — skipping)"
fi
echo ""

# ── Delete AgentCore runtime (releases VPC ENIs before VPC teardown) ───────
echo "── Deleting AgentCore runtime ────────────────────────────"
RUNTIME_ID=$(aws cloudformation describe-stacks \
  --stack-name "$(_sn Runtimes)" \
  --region "${AWS_REGION}" \
  --query "Stacks[0].Outputs[?OutputKey=='OrchestratorRuntimeId'].OutputValue" \
  --output text 2>/dev/null || true)

if [ -n "${RUNTIME_ID}" ] && [ "${RUNTIME_ID}" != "None" ]; then
  echo "  → Deleting AgentCore runtime ${RUNTIME_ID}..."

  # Delete all endpoints first (required before runtime deletion)
  ENDPOINTS=$(aws bedrock-agentcore list-agent-runtime-endpoints \
    --agent-runtime-id "${RUNTIME_ID}" \
    --region "${AWS_REGION}" \
    --query "agentRuntimeEndpoints[].name" \
    --output text 2>/dev/null || true)
  for ep in ${ENDPOINTS}; do
    if [ "${ep}" != "DEFAULT" ] && [ "${ep}" != "None" ] && [ -n "${ep}" ]; then
      aws bedrock-agentcore delete-agent-runtime-endpoint \
        --agent-runtime-id "${RUNTIME_ID}" \
        --endpoint-name "${ep}" \
        --region "${AWS_REGION}" 2>/dev/null || true
      echo "    ✓ Deleted endpoint ${ep}"
    fi
  done

  aws bedrock-agentcore delete-agent-runtime \
    --agent-runtime-id "${RUNTIME_ID}" \
    --region "${AWS_REGION}" 2>/dev/null || true

  # Wait for runtime to be fully deleted and ENIs to release
  echo "  → Waiting for runtime deletion and ENI release..."
  for i in $(seq 1 36); do
    RT_STATUS=$(aws bedrock-agentcore get-agent-runtime \
      --agent-runtime-id "${RUNTIME_ID}" \
      --region "${AWS_REGION}" \
      --query "status" \
      --output text 2>/dev/null || echo "DELETED")
    if [ "${RT_STATUS}" = "DELETED" ] || [ "${RT_STATUS}" = "NOT_FOUND" ]; then
      echo "    ✓ Runtime deleted"
      break
    fi
    echo "    $(date '+%H:%M:%S') — runtime status: ${RT_STATUS} (${i}/36)"
    sleep 10
  done

  # Poll VPC ENIs until AgentCore releases them (up to 6 minutes)
  if [ -n "${VPC_ID}" ] && [ "${VPC_ID}" != "None" ]; then
    echo "  → Waiting for AgentCore ENIs to release..."
    for i in $(seq 1 36); do
      AC_ENIS=$(aws ec2 describe-network-interfaces \
        --filters \
          Name=vpc-id,Values="${VPC_ID}" \
          Name=interface-type,Values="agentic_ai" \
          Name=group-id,Values="$(aws ec2 describe-security-groups \
            --filters Name=vpc-id,Values="${VPC_ID}" Name=group-name,Values="media-contracts-runtime-sg-${DEPLOYMENT_ID}-${STACK_SUFFIX}" \
            --region "${AWS_REGION}" \
            --query "SecurityGroups[0].GroupId" --output text 2>/dev/null || echo 'none')" \
        --region "${AWS_REGION}" \
        --query "NetworkInterfaces[].NetworkInterfaceId" \
        --output text 2>/dev/null || true)

      if [ -z "${AC_ENIS}" ] || [ "${AC_ENIS}" = "None" ] || [ "${AC_ENIS}" = "none" ]; then
        echo "    ✓ All AgentCore ENIs released"
        break
      fi

      # Try deleting any that are now available
      for eni_id in ${AC_ENIS}; do
        ENI_STATUS=$(aws ec2 describe-network-interfaces \
          --network-interface-ids "${eni_id}" \
          --region "${AWS_REGION}" \
          --query "NetworkInterfaces[0].Status" \
          --output text 2>/dev/null || echo "gone")
        if [ "${ENI_STATUS}" = "available" ]; then
          aws ec2 delete-network-interface --network-interface-id "${eni_id}" --region "${AWS_REGION}" 2>/dev/null || true
          echo "    ✓ Deleted ENI ${eni_id}"
        fi
      done

      # If we've waited 5+ minutes and ENIs are still attached, try forced detachment
      if [ $i -ge 30 ] && [ -n "${AC_ENIS}" ] && [ "${AC_ENIS}" != "none" ]; then
        echo "    ⚠️  AgentCore ENIs still attached after 5 minutes, attempting forced detachment..."
        for eni_id in ${AC_ENIS}; do
          ATTACHMENT_ID=$(aws ec2 describe-network-interfaces \
            --network-interface-ids "${eni_id}" \
            --region "${AWS_REGION}" \
            --query "NetworkInterfaces[0].Attachment.AttachmentId" \
            --output text 2>/dev/null || echo "")
          if [ -n "${ATTACHMENT_ID}" ] && [ "${ATTACHMENT_ID}" != "None" ]; then
            aws ec2 detach-network-interface \
              --attachment-id "${ATTACHMENT_ID}" \
              --force \
              --region "${AWS_REGION}" 2>/dev/null || true
            echo "    ⚠️  Force detached ${eni_id}"
          fi
        done
      fi

      echo "    $(date '+%H:%M:%S') — AgentCore ENIs still attached (${i}/36, waiting 10s)"
      sleep 10
    done
  fi
else
  echo "  (no AgentCore runtime found — skipping)"
fi
echo ""

# ── Final ENI verification before stack destruction ───────────────────────
echo "── Final ENI verification ────────────────────────────────"
if [ -n "${VPC_ID}" ] && [ "${VPC_ID}" != "None" ]; then
  log_info "Checking for any remaining ENIs in VPC ${VPC_ID}..."

  ALL_ENIS=$(aws ec2 describe-network-interfaces \
    --filters Name=vpc-id,Values="${VPC_ID}" \
    --region "${AWS_REGION}" \
    --query "NetworkInterfaces[].{ID:NetworkInterfaceId,Type:InterfaceType,Desc:Description,Status:Status}" \
    --output text 2>/dev/null || true)

  if [ -n "${ALL_ENIS}" ] && [ "${ALL_ENIS}" != "None" ]; then
    log_warn "Found remaining ENIs in VPC:"
    echo "${ALL_ENIS}" | while IFS=$'\t' read -r eni_id eni_type eni_desc eni_status; do
      echo "      ${eni_id} [${eni_type}] - ${eni_desc} (${eni_status})"
    done

    log_info "Attempting aggressive ENI cleanup..."

    # Delete VPC interface endpoints first (they own ENIs)
    log_info "Deleting VPC interface endpoints..."
    ENDPOINT_IDS=$(aws ec2 describe-vpc-endpoints \
      --filters Name=vpc-id,Values="${VPC_ID}" Name=vpc-endpoint-type,Values="Interface" \
      --region "${AWS_REGION}" \
      --query "VpcEndpoints[].VpcEndpointId" \
      --output text 2>/dev/null || true)

    if [ -n "${ENDPOINT_IDS}" ] && [ "${ENDPOINT_IDS}" != "None" ]; then
      for ep_id in ${ENDPOINT_IDS}; do
        aws ec2 delete-vpc-endpoints --vpc-endpoint-ids "${ep_id}" --region "${AWS_REGION}" 2>/dev/null || true
        log_info "Deleted VPC endpoint ${ep_id}"
      done
      # Wait for endpoint ENIs to release (up to 2 minutes)
      for i in $(seq 1 12); do
        sleep 10
        ENDPOINT_ENIS=$(aws ec2 describe-network-interfaces \
          --filters Name=vpc-id,Values="${VPC_ID}" Name=interface-type,Values="vpc_endpoint" \
          --region "${AWS_REGION}" \
          --query "NetworkInterfaces[].NetworkInterfaceId" \
          --output text 2>/dev/null || true)
        if [ -z "${ENDPOINT_ENIS}" ] || [ "${ENDPOINT_ENIS}" = "None" ]; then
          log_success "VPC endpoint ENIs released"
          break
        fi
        echo "    $(date '+%H:%M:%S') — Waiting for VPC endpoint ENIs to release (${i}/12)"
      done
    fi

    # Force detach and delete any remaining ENIs
    for i in $(seq 1 12); do
      REMAINING_ENIS=$(aws ec2 describe-network-interfaces \
        --filters Name=vpc-id,Values="${VPC_ID}" \
        --region "${AWS_REGION}" \
        --query "NetworkInterfaces[].[NetworkInterfaceId,Status,Attachment.AttachmentId]" \
        --output text 2>/dev/null || true)

      if [ -z "${REMAINING_ENIS}" ] || [ "${REMAINING_ENIS}" = "None" ]; then
        log_success "All ENIs cleaned up"
        break
      fi

      echo "${REMAINING_ENIS}" | while IFS=$'\t' read -r eni_id eni_status attachment_id; do
        if [ "${eni_status}" = "available" ]; then
          aws ec2 delete-network-interface --network-interface-id "${eni_id}" --region "${AWS_REGION}" 2>/dev/null && \
            log_info "Deleted available ENI ${eni_id}" || true
        elif [ -n "${attachment_id}" ] && [ "${attachment_id}" != "None" ]; then
          log_warn "Force detaching ENI ${eni_id}..."
          aws ec2 detach-network-interface --attachment-id "${attachment_id}" --force --region "${AWS_REGION}" 2>/dev/null || true
          sleep 2
          aws ec2 delete-network-interface --network-interface-id "${eni_id}" --region "${AWS_REGION}" 2>/dev/null && \
            log_info "Deleted ENI ${eni_id}" || true
        fi
      done

      sleep 5
    done

    # Final check
    FINAL_ENIS=$(aws ec2 describe-network-interfaces \
      --filters Name=vpc-id,Values="${VPC_ID}" \
      --region "${AWS_REGION}" \
      --query "NetworkInterfaces[].NetworkInterfaceId" \
      --output text 2>/dev/null || true)

    if [ -n "${FINAL_ENIS}" ] && [ "${FINAL_ENIS}" != "None" ]; then
      log_error "Unable to clean up all ENIs. VPC deletion may fail."
      log_error "Remaining ENIs: ${FINAL_ENIS}"
      log_warn "VPC stack will use auto-fix fallback (retain failed resources)"
    else
      log_success "All ENIs successfully cleaned up"
    fi
  else
    log_success "No ENIs found in VPC - clean state"
  fi
else
  log_info "VPC ID not found, skipping ENI check"
fi
echo ""

# ── Destroy all stacks ─────────────────────────────────────────────────────
echo "── Destroying CloudFormation stacks ──────────────────────"
export CDK_DEFAULT_ACCOUNT="${ACCOUNT_ID}"
export CDK_DEFAULT_REGION="${AWS_REGION}"
export MODEL_ID="${MODEL_ID:-us.anthropic.claude-sonnet-4-6}"
export IMAGE_TAG="${IMAGE_TAG:-latest}"

(cd deployment && uv run cdk destroy --app "python app.py" --force \
  "${STACKS[@]}")
echo ""

# ── Schedule KMS key for deletion ──────────────────────────────────────────
if [ -n "${KMS_KEY_ARN}" ]; then
  echo "── Scheduling KMS key deletion ───────────────────────────"
  STATUS=$(aws kms describe-key --key-id "${KMS_KEY_ARN}" --region "${AWS_REGION}" \
    --query 'KeyMetadata.KeyState' --output text 2>/dev/null || echo "MISSING")

  case "${STATUS}" in
    PendingDeletion)
      DELETION_DATE=$(aws kms describe-key --key-id "${KMS_KEY_ARN}" --region "${AWS_REGION}" \
        --query 'KeyMetadata.DeletionDate' --output text)
      echo "  ✓ KMS key already scheduled for deletion on ${DELETION_DATE}"
      ;;
    Enabled|Disabled)
      aws kms schedule-key-deletion \
        --key-id "${KMS_KEY_ARN}" \
        --pending-window-in-days "${KMS_WAIT_DAYS}" \
        --region "${AWS_REGION}" \
        --output text --no-cli-pager > /dev/null
      echo "  ✓ KMS key ${KMS_KEY_ARN} scheduled for deletion in ${KMS_WAIT_DAYS} days"
      echo "    (run 'aws kms cancel-key-deletion --key-id ${KMS_KEY_ARN}' to cancel)"
      ;;
    MISSING)
      echo "  (KMS key ${KMS_KEY_ARN} not found — skipping)"
      ;;
    *)
      echo "  ⚠️  KMS key is in state ${STATUS} — not modifying."
      ;;
  esac
  echo ""
fi

# ── Verify stacks are gone ─────────────────────────────────────────────────
echo "── Verifying stack deletion ──────────────────────────────"
REMAINING=()
for stack in "${STACKS[@]}"; do
  STATE=$(aws cloudformation describe-stacks \
    --stack-name "${stack}" \
    --region "${AWS_REGION}" \
    --query 'Stacks[0].StackStatus' \
    --output text 2>/dev/null || echo "DELETED")
  if [ "${STATE}" != "DELETED" ]; then
    REMAINING+=("${stack} (${STATE})")
  fi
done

if [ ${#REMAINING[@]} -eq 0 ]; then
  echo "  ✓ All stacks deleted"
else
  echo "  ⚠️  The following stacks still exist:"
  for s in "${REMAINING[@]}"; do echo "      - ${s}"; done

  # Auto-fix stuck VPC stack by retaining failed resources then cleaning up
  VPC_STACK="$(_sn Vpc)"
  VPC_STATE=$(aws cloudformation describe-stacks \
    --stack-name "${VPC_STACK}" \
    --region "${AWS_REGION}" \
    --query 'Stacks[0].StackStatus' \
    --output text 2>/dev/null || echo "DELETED")

  if [ "${VPC_STATE}" = "DELETE_FAILED" ]; then
    echo ""
    echo "── Auto-fixing stuck VPC stack ─────────────────────────"
    FAILED_RESOURCES=$(aws cloudformation list-stack-resources \
      --stack-name "${VPC_STACK}" \
      --region "${AWS_REGION}" \
      --query "StackResourceSummaries[?ResourceStatus=='DELETE_FAILED'].LogicalResourceId" \
      --output text 2>/dev/null || true)

    if [ -n "${FAILED_RESOURCES}" ]; then
      echo "  → Retrying delete with --retain-resources: ${FAILED_RESOURCES}"
      # shellcheck disable=SC2086
      aws cloudformation delete-stack \
        --stack-name "${VPC_STACK}" \
        --retain-resources ${FAILED_RESOURCES} \
        --region "${AWS_REGION}"

      echo "  → Waiting for stack deletion..."
      aws cloudformation wait stack-delete-complete \
        --stack-name "${VPC_STACK}" \
        --region "${AWS_REGION}" 2>/dev/null || true

      # Now clean up the retained resources
      echo "  → Cleaning up retained VPC resources..."

      # Wait for any remaining ENIs to release
      for i in $(seq 1 18); do
        ORPHAN_ENIS=$(aws ec2 describe-network-interfaces \
          --filters Name=group-name,Values="media-contracts-*-${DEPLOYMENT_ID}-${STACK_SUFFIX}" \
          --region "${AWS_REGION}" \
          --query "NetworkInterfaces[].{ID:NetworkInterfaceId,Status:Status}" \
          --output text 2>/dev/null || true)

        if [ -z "${ORPHAN_ENIS}" ] || [ "${ORPHAN_ENIS}" = "None" ]; then
          break
        fi

        # Delete any that are available
        while IFS=$'\t' read -r eni_id eni_status; do
          if [ "${eni_status}" = "available" ]; then
            aws ec2 delete-network-interface --network-interface-id "${eni_id}" --region "${AWS_REGION}" 2>/dev/null || true
            echo "    ✓ Deleted ENI ${eni_id}"
          fi
        done <<< "${ORPHAN_ENIS}"

        echo "    $(date '+%H:%M:%S') — waiting for ENIs to release (${i}/18)"
        sleep 10
      done

      # Delete retained subnets
      for subnet_id in $(aws ec2 describe-subnets \
        --filters Name=tag:project,Values=media-contracts Name=tag:deployment_id,Values="${DEPLOYMENT_ID}" \
        --region "${AWS_REGION}" \
        --query "Subnets[].SubnetId" --output text 2>/dev/null || true); do
        aws ec2 delete-subnet --subnet-id "${subnet_id}" --region "${AWS_REGION}" 2>/dev/null && \
          echo "    ✓ Deleted subnet ${subnet_id}" || \
          echo "    ⚠️  Could not delete subnet ${subnet_id}"
      done

      # Delete retained security groups (skip default SG)
      for sg_id in $(aws ec2 describe-security-groups \
        --filters Name=tag:project,Values=media-contracts Name=tag:deployment_id,Values="${DEPLOYMENT_ID}" \
        --region "${AWS_REGION}" \
        --query "SecurityGroups[].GroupId" --output text 2>/dev/null || true); do
        aws ec2 delete-security-group --group-id "${sg_id}" --region "${AWS_REGION}" 2>/dev/null && \
          echo "    ✓ Deleted SG ${sg_id}" || \
          echo "    ⚠️  Could not delete SG ${sg_id}"
      done

      # Delete the VPC itself if still around
      RETAINED_VPC=$(aws ec2 describe-vpcs \
        --filters Name=tag:project,Values=media-contracts Name=tag:deployment_id,Values="${DEPLOYMENT_ID}" \
        --region "${AWS_REGION}" \
        --query "Vpcs[0].VpcId" --output text 2>/dev/null || true)
      if [ -n "${RETAINED_VPC}" ] && [ "${RETAINED_VPC}" != "None" ]; then
        # Delete any remaining internet gateways
        for igw_id in $(aws ec2 describe-internet-gateways \
          --filters Name=attachment.vpc-id,Values="${RETAINED_VPC}" \
          --region "${AWS_REGION}" \
          --query "InternetGateways[].InternetGatewayId" --output text 2>/dev/null || true); do
          aws ec2 detach-internet-gateway --internet-gateway-id "${igw_id}" --vpc-id "${RETAINED_VPC}" --region "${AWS_REGION}" 2>/dev/null || true
          aws ec2 delete-internet-gateway --internet-gateway-id "${igw_id}" --region "${AWS_REGION}" 2>/dev/null || true
          echo "    ✓ Deleted IGW ${igw_id}"
        done

        aws ec2 delete-vpc --vpc-id "${RETAINED_VPC}" --region "${AWS_REGION}" 2>/dev/null && \
          echo "    ✓ Deleted VPC ${RETAINED_VPC}" || \
          echo "    ⚠️  Could not delete VPC ${RETAINED_VPC} — may need manual cleanup"
      fi

      echo "  ✓ VPC cleanup complete"
    fi
  fi
fi
echo ""

echo "════════════════════════════════════════════════════════"
echo "  ✅ Teardown complete  (DEPLOYMENT_ID=${DEPLOYMENT_ID}, STACK_SUFFIX=${STACK_SUFFIX})"
echo "════════════════════════════════════════════════════════"
