"""IAM Stack for MediaContracts.

Creates the orchestrator AgentCore Runtime execution role.
Specialist Lambda roles are in SpecialistLambdasStack.
"""

from aws_cdk import (
    Stack,
    Tags,
    CfnOutput,
    aws_iam as iam,
    aws_s3 as s3,
    aws_dynamodb as dynamodb,
)
from constructs import Construct
from cdk_nag import NagSuppressions

BEDROCK_FOUNDATION_MODELS = [
    "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6",
    "arn:aws:bedrock:*::foundation-model/anthropic.claude-opus-4-6-v1",
    "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0",
    "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
]

BEDROCK_INFERENCE_PROFILES = [
    "us.anthropic.claude-sonnet-4-6",
    "us.anthropic.claude-opus-4-6-v1",
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
]


class IAMStack(Stack):
    """Orchestrator execution role."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        deployment_id: str,
        stack_suffix: str,
        deployment_tags: dict[str, str],
        config_bucket: s3.Bucket,
        source_bucket: s3.Bucket,
        results_bucket: s3.Bucket,
        jobs_table: dynamodb.Table,
        kms_key_arn: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.deployment_id = deployment_id
        self.deployment_tags = deployment_tags
        self._apply_common_tags()

        self.orchestrator_role = iam.Role(
            self,
            "OrchestratorRole",
            role_name=f"media-contracts-orchestrator-{deployment_id}-{stack_suffix}",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            description="Execution role for MediaContracts orchestrator AgentCore Runtime",
        )

        # Bedrock model invocation
        self.orchestrator_role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockInvoke",
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:CountTokens",
                ],
                resources=BEDROCK_FOUNDATION_MODELS
                + [
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/{profile}"
                    for profile in BEDROCK_INFERENCE_PROFILES
                ],
            )
        )

        # aws-marketplace:Subscribe is required on first deploy if the Bedrock model
        # EULA has not yet been accepted in this account. Remove after EULA acceptance.
        self.orchestrator_role.add_to_policy(
            iam.PolicyStatement(
                sid="MarketplaceSubscription",
                actions=[
                    "aws-marketplace:ViewSubscriptions",
                    "aws-marketplace:Subscribe",
                ],
                resources=["*"],
            )
        )

        # ECR image pull
        self.orchestrator_role.add_to_policy(
            iam.PolicyStatement(
                sid="ECRAccess",
                actions=[
                    "ecr:BatchGetImage",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:GetAuthorizationToken",
                ],
                resources=["*"],
            )
        )

        # S3 — scoped to specific prefixes the orchestrator actually reads/writes.
        # Config bucket: read prompts under prompts/foundation/ and prompts/agents/
        self.orchestrator_role.add_to_policy(
            iam.PolicyStatement(
                sid="ConfigPromptsRead",
                actions=["s3:GetObject"],
                resources=[
                    f"{config_bucket.bucket_arn}/prompts/foundation/*",
                    f"{config_bucket.bucket_arn}/prompts/agents/*",
                ],
            )
        )
        self.orchestrator_role.add_to_policy(
            iam.PolicyStatement(
                sid="ConfigPromptsList",
                actions=["s3:ListBucket"],
                resources=[config_bucket.bucket_arn],
                conditions={
                    "StringLike": {
                        "s3:prefix": [
                            "prompts/foundation/*",
                            "prompts/agents/*",
                            "prompts/foundation",
                            "prompts/agents",
                        ]
                    }
                },
            )
        )

        # Source bucket: read uploaded contract PDFs
        self.orchestrator_role.add_to_policy(
            iam.PolicyStatement(
                sid="SourceContractsRead",
                actions=["s3:GetObject"],
                resources=[f"{source_bucket.bucket_arn}/*"],
            )
        )

        # Results bucket: read + write under the two canonical prefixes only.
        # jobs-canonical-versions/<job_id>/... : XML + MD originals + metadata sidecars
        # jobs-kb-versions/<job_id>/...         : TXT + MD KB copies + metadata sidecars
        self.orchestrator_role.add_to_policy(
            iam.PolicyStatement(
                sid="ResultsReadWrite",
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                ],
                resources=[
                    f"{results_bucket.bucket_arn}/jobs-canonical-versions/*",
                    f"{results_bucket.bucket_arn}/jobs-kb-versions/*",
                ],
            )
        )
        self.orchestrator_role.add_to_policy(
            iam.PolicyStatement(
                sid="ResultsList",
                actions=["s3:ListBucket"],
                resources=[results_bucket.bucket_arn],
                conditions={
                    "StringLike": {
                        "s3:prefix": [
                            "jobs-canonical-versions/*",
                            "jobs-kb-versions/*",
                        ]
                    }
                },
            )
        )

        # DynamoDB
        jobs_table.grant_read_write_data(self.orchestrator_role)

        # KMS
        self.orchestrator_role.add_to_policy(
            iam.PolicyStatement(
                sid="KMSDecrypt",
                actions=["kms:Decrypt", "kms:GenerateDataKey"],
                resources=[kms_key_arn],
            )
        )

        # CloudWatch Logs
        self.orchestrator_role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudWatchLogs",
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=[
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/bedrock-agentcore/runtimes/*"
                ],
            )
        )

        # X-Ray
        self.orchestrator_role.add_to_policy(
            iam.PolicyStatement(
                sid="XRay",
                actions=[
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",
                ],
                resources=["*"],
            )
        )

        # SSM
        self.orchestrator_role.add_to_policy(
            iam.PolicyStatement(
                sid="SSMParameters",
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/mc-{stack_suffix}/*"
                ],
            )
        )

        # Secrets Manager — Cognito credentials for Gateway auth
        self.orchestrator_role.add_to_policy(
            iam.PolicyStatement(
                sid="SecretsManager",
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:mc-{stack_suffix}/*"
                ],
            )
        )

        # CloudWatch custom metrics (emit_job_metrics)
        self.orchestrator_role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudWatchMetrics",
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
                conditions={
                    "StringEquals": {"cloudwatch:namespace": "MediaContracts/Pipeline"}
                },
            )
        )

        CfnOutput(
            self,
            "OrchestratorRoleArn",
            value=self.orchestrator_role.role_arn,
            export_name=f"{self.stack_name}-OrchestratorRoleArn",
        )

        # ── CDK Nag suppressions ───────────────────────────────────
        # Helper to get the CloudFormation logical ID for cross-stack L2 constructs
        def _logical_id(construct) -> str:
            return Stack.of(construct).get_logical_id(construct.node.default_child)

        NagSuppressions.add_resource_suppressions(
            self.orchestrator_role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "ecr:GetAuthorizationToken requires * — AWS does not support resource-level restrictions for this action.",
                    "appliesTo": ["Resource::*"],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "xray:PutTraceSegments and related X-Ray actions require * — no resource-level support.",
                    "appliesTo": ["Resource::*"],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "cloudwatch:PutMetricData is restricted by a StringEquals condition on namespace MediaContracts/Pipeline — wildcard resource is required by the service.",
                    "appliesTo": ["Resource::*"],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "aws-marketplace:Subscribe required for Bedrock model EULA acceptance on first deploy. Remove after EULA is accepted in this account.",
                    "appliesTo": ["Resource::*"],
                },
            ],
            apply_to_children=True,
        )

        # IAM5 suppressions for prefix-scoped S3 wildcards
        _config_id = _logical_id(config_bucket)
        _source_id = _logical_id(source_bucket)
        _results_id = _logical_id(results_bucket)
        _jobs_id = _logical_id(jobs_table)

        NagSuppressions.add_resource_suppressions(
            self.orchestrator_role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "S3 object paths use prefix-scoped wildcards (e.g., /prompts/foundation/*) — "
                    "individual object keys are dynamic and cannot be enumerated at deploy time.",
                    "appliesTo": [
                        f"Resource::<{_config_id}.Arn>/prompts/foundation/*",
                        f"Resource::<{_config_id}.Arn>/prompts/agents/*",
                        f"Resource::<{_source_id}.Arn>/*",
                        f"Resource::<{_results_id}.Arn>/jobs-canonical-versions/*",
                        f"Resource::<{_results_id}.Arn>/jobs-kb-versions/*",
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "CDK grant_read_write_data() adds /index/* suffix for GSI access — "
                    "table ARN is already scoped to the specific jobs table.",
                    "appliesTo": [f"Resource::<{_jobs_id}.Arn>/index/*"],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "Bedrock cross-region inference requires region wildcard in model ARNs — "
                    "scoped to specific named foundation models and inference profiles.",
                    "appliesTo": [
                        f"Resource::{arn}" for arn in BEDROCK_FOUNDATION_MODELS
                    ]
                    + [
                        f"Resource::arn:aws:bedrock:*:<AWS::AccountId>:inference-profile/{profile}"
                        for profile in BEDROCK_INFERENCE_PROFILES
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "AgentCore runtime log group names include a runtime ID generated at deploy time — "
                    "prefix-scoped to /aws/bedrock-agentcore/runtimes/.",
                    "appliesTo": [
                        f"Resource::arn:aws:logs:{self.region}:<AWS::AccountId>:log-group:/aws/bedrock-agentcore/runtimes/*",
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "Secret names include a random suffix appended by Secrets Manager — "
                    "prefix-scoped to mc-{stack_suffix}/.",
                    "appliesTo": [
                        f"Resource::arn:aws:secretsmanager:{self.region}:<AWS::AccountId>:secret:mc-{stack_suffix}/*",
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "SSM parameters are prefix-scoped to /mc-{stack_suffix}/ — individual "
                    "parameter names are written by other stacks and discovered at runtime.",
                    "appliesTo": [
                        f"Resource::arn:aws:ssm:{self.region}:<AWS::AccountId>:parameter/mc-{stack_suffix}/*",
                    ],
                },
            ],
            apply_to_children=True,
        )

    def _apply_common_tags(self) -> None:
        for k, v in self.deployment_tags.items():
            Tags.of(self).add(k, v)
