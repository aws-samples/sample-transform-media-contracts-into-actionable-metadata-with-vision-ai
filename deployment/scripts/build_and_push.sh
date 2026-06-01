#!/usr/bin/env bash
# Build and push the MediaContracts orchestrator container to ECR.
# Must be run from the repo root.
#
# Usage:
#   DEPLOYMENT_ID=dev AWS_REGION=us-west-2 ./deployment/scripts/build_and_push.sh
#   IMAGE_TAG=v1.2.0 DEPLOYMENT_ID=prod ./deployment/scripts/build_and_push.sh

set -euo pipefail

DEPLOYMENT_ID="${DEPLOYMENT_ID:-dev}"
AWS_REGION="${AWS_REGION:-us-west-2}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ECR_BASE="${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"
REPO="media-contracts-orchestrator-${DEPLOYMENT_ID}"
IMAGE_URI="${ECR_BASE}/${REPO}:${IMAGE_TAG}"

echo "==> Authenticating with ECR"
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${ECR_BASE}"

echo "==> Building orchestrator → ${IMAGE_URI}"
docker buildx build \
  --platform linux/arm64 \
  --file agentcore/orchestrator/Dockerfile \
  --tag "${IMAGE_URI}" \
  --push \
  .

echo ""
echo "✓ Pushed ${IMAGE_URI}"
echo ""
echo "Deploy with:"
echo "  IMAGE_TAG=${IMAGE_TAG} DEPLOYMENT_ID=${DEPLOYMENT_ID} cdk deploy MediaContractsRuntimes"
