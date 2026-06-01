"""Inference Profiles Stack for MediaContracts.

Creates Application Inference Profiles for cost tracking and usage monitoring.
Profile ARNs are passed to the orchestrator runtime and specialist Lambdas
so all Bedrock calls are attributed to this application.

Model IDs confirmed from AWS docs (April 2026):
  Claude Sonnet 4.6 : anthropic.claude-sonnet-4-6          (no date/version suffix)
  Claude Opus 4.6   : anthropic.claude-opus-4-6-v1          (v1 suffix, no date)
  Claude Sonnet 4.5 : anthropic.claude-sonnet-4-5-20250929-v1:0
  Claude Haiku 4.5  : anthropic.claude-haiku-4-5-20251001-v1:0

Geo inference IDs (us.* prefix for us-west-2):
  us.anthropic.claude-sonnet-4-6
  us.anthropic.claude-opus-4-6-v1
  us.anthropic.claude-sonnet-4-5-20250929-v1:0
  us.anthropic.claude-haiku-4-5-20251001-v1:0
"""

from aws_cdk import (
    Stack,
    Tags,
    CfnOutput,
    aws_iam as iam,
)
from aws_cdk.aws_bedrock import CfnApplicationInferenceProfile
from constructs import Construct

# Geo inference profile IDs (us.* avoids SCP issues with global.* cross-region)
GEO_PROFILES = {
    "sonnet_46": "us.anthropic.claude-sonnet-4-6",
    "opus_46": "us.anthropic.claude-opus-4-6-v1",
    "sonnet_45": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "haiku_45": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
}

# Underlying foundation model IDs (required for IAM alongside inference profiles)
FOUNDATION_MODELS = {
    "sonnet_46": "anthropic.claude-sonnet-4-6",
    "opus_46": "anthropic.claude-opus-4-6-v1",
    "sonnet_45": "anthropic.claude-sonnet-4-5-20250929-v1:0",
    "haiku_45": "anthropic.claude-haiku-4-5-20251001-v1:0",
}


class InferenceProfilesStack(Stack):
    """Application Inference Profiles for cost tracking."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        deployment_id: str,
        stack_suffix: str,
        deployment_tags: dict[str, str],
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.deployment_id = deployment_id
        self.deployment_tags = deployment_tags
        self._apply_common_tags()

        cfn_tags = [{"key": k, "value": v} for k, v in deployment_tags.items()]

        def _profile(
            logical_id: str, key: str, description: str
        ) -> CfnApplicationInferenceProfile:
            return CfnApplicationInferenceProfile(
                self,
                logical_id,
                inference_profile_name=f"media-contracts-{key.replace('_', '-')}-{deployment_id}-{stack_suffix}",
                model_source=CfnApplicationInferenceProfile.InferenceProfileModelSourceProperty(
                    copy_from=(
                        f"arn:aws:bedrock:{self.region}:{self.account}"
                        f":inference-profile/{GEO_PROFILES[key]}"
                    )
                ),
                description=description,
                tags=cfn_tags,
            )

        self._sonnet_46 = _profile(
            "Sonnet46Profile",
            "sonnet_46",
            "Claude Sonnet 4.6 primary model for MediaContracts pipeline",
        )
        self._opus_46 = _profile(
            "Opus46Profile", "opus_46", "Claude Opus 4.6 complex analysis fallback"
        )
        self._sonnet_45 = _profile(
            "Sonnet45Profile", "sonnet_45", "Claude Sonnet 4.5 fallback"
        )
        self._haiku_45 = _profile(
            "Haiku45Profile", "haiku_45", "Claude Haiku 4.5 lightweight fallback"
        )

        CfnOutput(
            self,
            "Sonnet46Arn",
            value=self._sonnet_46.attr_inference_profile_arn,
            export_name=f"{self.stack_name}-Sonnet46Arn",
        )
        CfnOutput(
            self,
            "Opus46Arn",
            value=self._opus_46.attr_inference_profile_arn,
            export_name=f"{self.stack_name}-Opus46Arn",
        )
        CfnOutput(
            self,
            "Sonnet45Arn",
            value=self._sonnet_45.attr_inference_profile_arn,
            export_name=f"{self.stack_name}-Sonnet45Arn",
        )
        CfnOutput(
            self,
            "Haiku45Arn",
            value=self._haiku_45.attr_inference_profile_arn,
            export_name=f"{self.stack_name}-Haiku45Arn",
        )

    # ── ARN properties ──────────────────────────────────────────────

    @property
    def sonnet_46_arn(self) -> str:
        return str(self._sonnet_46.attr_inference_profile_arn)

    @property
    def opus_46_arn(self) -> str:
        return str(self._opus_46.attr_inference_profile_arn)

    @property
    def sonnet_45_arn(self) -> str:
        return str(self._sonnet_45.attr_inference_profile_arn)

    @property
    def haiku_45_arn(self) -> str:
        return str(self._haiku_45.attr_inference_profile_arn)

    # ── IAM grant ───────────────────────────────────────────────────

    def grant_invoke_to_role(self, role: iam.Role) -> None:
        """Grant invoke permissions on all profiles + underlying models to a role."""
        # Application inference profiles
        role.add_to_policy(
            iam.PolicyStatement(
                sid="InvokeApplicationProfiles",
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:CountTokens",
                ],
                resources=[
                    self._sonnet_46.attr_inference_profile_arn,
                    self._opus_46.attr_inference_profile_arn,
                    self._sonnet_45.attr_inference_profile_arn,
                    self._haiku_45.attr_inference_profile_arn,
                ],
            )
        )
        # Geo inference profiles (system-defined, required alongside app profiles)
        role.add_to_policy(
            iam.PolicyStatement(
                sid="InvokeGeoProfiles",
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:CountTokens",
                ],
                resources=[
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/{GEO_PROFILES['sonnet_46']}",
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/{GEO_PROFILES['opus_46']}",
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/{GEO_PROFILES['sonnet_45']}",
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/{GEO_PROFILES['haiku_45']}",
                ],
            )
        )
        # Foundation models (required per AWS docs when using inference profiles)
        role.add_to_policy(
            iam.PolicyStatement(
                sid="InvokeFoundationModels",
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:CountTokens",
                ],
                resources=[
                    f"arn:aws:bedrock:*::foundation-model/{FOUNDATION_MODELS['sonnet_46']}",
                    f"arn:aws:bedrock:*::foundation-model/{FOUNDATION_MODELS['opus_46']}",
                    f"arn:aws:bedrock:*::foundation-model/{FOUNDATION_MODELS['sonnet_45']}",
                    f"arn:aws:bedrock:*::foundation-model/{FOUNDATION_MODELS['haiku_45']}",
                ],
            )
        )

    def _apply_common_tags(self) -> None:
        for k, v in self.deployment_tags.items():
            Tags.of(self).add(k, v)
