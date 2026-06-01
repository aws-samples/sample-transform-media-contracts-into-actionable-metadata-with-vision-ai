"""Specialist Lambdas Stack for MediaContracts.

Each specialist (financial, rights_clearance, etc.) is a Lambda function
that serves as an MCP tool target behind the AgentCore Gateway.

The Lambda receives the contract extraction text, runs the specialist
Strands agent with its S3-loaded prompt, writes XML output to S3,
updates DynamoDB, and returns the result.

All functions share the same code package — the specialist name is
passed as an environment variable (SPECIALIST_NAME) to select the
correct prompt from S3.
"""

from aws_cdk import (
    BundlingOptions,
    Duration,
    Stack,
    Tags,
    CfnOutput,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_sqs as sqs,
    aws_s3 as s3,
    aws_dynamodb as dynamodb,
)
from constructs import Construct
from cdk_nag import NagSuppressions

SPECIALISTS = [
    "financial",
    "rights_clearance",
    "talent_guild_compliance",
    "regulatory_compliance",
    "risk_strategist",
    "handwriting_analyzer",
]


class SpecialistLambdasStack(Stack):
    """Lambda functions for each MediaContracts specialist."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        deployment_id: str,
        stack_suffix: str,
        deployment_tags: dict[str, str],
        config_bucket: s3.Bucket,
        results_bucket: s3.Bucket,
        jobs_table: dynamodb.Table,
        kms_key_arn: str,
        glossary_kb_id: str = "",
        model_id: str = "us.anthropic.claude-sonnet-4-6",
        max_tokens: int = 16000,
        sonnet_46_profile_arn: str = "",
        opus_46_profile_arn: str = "",
        sonnet_45_profile_arn: str = "",
        haiku_45_profile_arn: str = "",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.deployment_id = deployment_id
        self.deployment_tags = deployment_tags
        self._apply_common_tags()

        # ── Shared Lambda execution role ───────────────────────────
        self.lambda_role = iam.Role(
            self,
            "SpecialistLambdaRole",
            role_name=f"media-contracts-specialist-lambda-role-{deployment_id}-{stack_suffix}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description="Execution role for MediaContracts specialist Lambda functions",
        )

        # Bedrock agent runtime — KB Retrieve scoped to the specific glossary KB ARN
        if glossary_kb_id:
            self.lambda_role.add_to_policy(
                iam.PolicyStatement(
                    sid="BedrockKBRetrieve",
                    actions=["bedrock:Retrieve"],
                    resources=[
                        f"arn:aws:bedrock:{self.region}:{self.account}:knowledge-base/{glossary_kb_id}"
                    ],
                )
            )

        # Bedrock model invocation — narrowed to the specific foundation model
        # and the inference profile ARNs passed in.
        bedrock_resources = [
            "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6",
            f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/us.anthropic.claude-sonnet-4-6",
        ]
        # Include additional inference profile ARNs when provided
        for arn in (
            sonnet_46_profile_arn,
            opus_46_profile_arn,
            sonnet_45_profile_arn,
            haiku_45_profile_arn,
        ):
            if arn:
                bedrock_resources.append(arn)
        self.lambda_role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockInvoke",
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:CountTokens",
                ],
                resources=bedrock_resources,
            )
        )

        # S3 config read — PromptLoader uses ListObjectsV2 to discover XML files
        # under prompts/foundation/ and prompts/agents/{name}/, then GetObject to fetch them.
        # Also needs GetObject for tool schemas.
        self.lambda_role.add_to_policy(
            iam.PolicyStatement(
                sid="ConfigBucketList",
                actions=["s3:ListBucket"],
                resources=[config_bucket.bucket_arn],
                conditions={
                    "StringLike": {
                        "s3:prefix": [
                            "prompts/foundation/*",
                            "prompts/agents/*",
                        ]
                    }
                },
            )
        )
        prompt_object_arns = [
            f"{config_bucket.bucket_arn}/prompts/foundation/*",
            f"{config_bucket.bucket_arn}/prompts/agents/*",
        ]
        for specialist in SPECIALISTS:
            prompt_object_arns.append(
                f"{config_bucket.bucket_arn}/schemas/specialists/{specialist}.json"
            )
        self.lambda_role.add_to_policy(
            iam.PolicyStatement(
                sid="ConfigPromptsRead",
                actions=["s3:GetObject"],
                resources=prompt_object_arns,
            )
        )

        # S3 results write — scoped per specialist to exact object keys under both
        # canonical and KB prefixes (XML + TXT + metadata sidecars).
        # Canonical: jobs-canonical-versions/<job_id>/specialists/<name>.xml (+ .metadata.json)
        # KB:        jobs-kb-versions/<job_id>/specialists/<name>.txt (+ .metadata.json)
        results_object_arns = []
        for specialist in SPECIALISTS:
            results_object_arns.extend(
                [
                    f"{results_bucket.bucket_arn}/jobs-canonical-versions/*/specialists/{specialist}.xml",
                    f"{results_bucket.bucket_arn}/jobs-canonical-versions/*/specialists/{specialist}.xml.metadata.json",
                    f"{results_bucket.bucket_arn}/jobs-kb-versions/*/specialists/{specialist}.txt",
                    f"{results_bucket.bucket_arn}/jobs-kb-versions/*/specialists/{specialist}.txt.metadata.json",
                ]
            )
        self.lambda_role.add_to_policy(
            iam.PolicyStatement(
                sid="ResultsWrite",
                actions=["s3:PutObject", "s3:GetObject"],
                resources=results_object_arns,
            )
        )

        # S3 extraction read — specialists read per-page extraction files from S3
        self.lambda_role.add_to_policy(
            iam.PolicyStatement(
                sid="ExtractionReadObjects",
                actions=["s3:GetObject"],
                resources=[
                    f"{results_bucket.bucket_arn}/jobs-canonical-versions/*/extraction/*",
                ],
            )
        )
        self.lambda_role.add_to_policy(
            iam.PolicyStatement(
                sid="ExtractionListBucket",
                actions=["s3:ListBucket"],
                resources=[results_bucket.bucket_arn],
                conditions={
                    "StringLike": {
                        "s3:prefix": ["jobs-canonical-versions/*/extraction/*"]
                    }
                },
            )
        )

        # DynamoDB — explicit actions on the table itself and each named GSI.
        # GSIs are declared in DynamoDBStack: StatusIndex (ops monitoring).
        dynamo_actions = [
            "dynamodb:GetItem",
            "dynamodb:PutItem",
            "dynamodb:UpdateItem",
            "dynamodb:Query",
            "dynamodb:BatchGetItem",
            "dynamodb:BatchWriteItem",
            "dynamodb:ConditionCheckItem",
            "dynamodb:DescribeTable",
        ]
        self.lambda_role.add_to_policy(
            iam.PolicyStatement(
                sid="DynamoTable",
                actions=dynamo_actions,
                resources=[jobs_table.table_arn],
            )
        )
        self.lambda_role.add_to_policy(
            iam.PolicyStatement(
                sid="DynamoStatusIndex",
                actions=["dynamodb:Query"],
                resources=[f"{jobs_table.table_arn}/index/StatusIndex"],
            )
        )

        # KMS
        self.lambda_role.add_to_policy(
            iam.PolicyStatement(
                sid="KMS",
                actions=["kms:Decrypt", "kms:GenerateDataKey"],
                resources=[kms_key_arn],
            )
        )

        # X-Ray — required for ADOT layer to export traces
        self.lambda_role.add_to_policy(
            iam.PolicyStatement(
                sid="XRayWrite",
                actions=[
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",
                ],
                resources=["*"],
            )
        )

        # CloudWatch Logs — explicit scoped policies per specialist log group.
        specialist_log_group_arns = [
            f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/lambda/"
            f"media-contracts-specialist-{specialist.replace('_', '-')}-{deployment_id}-{stack_suffix}:*"
            for specialist in SPECIALISTS
        ]
        self.lambda_role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudWatchLogsStreams",
                actions=[
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=specialist_log_group_arns,
            )
        )

        # SSM — explicit parameter names the specialists read
        self.lambda_role.add_to_policy(
            iam.PolicyStatement(
                sid="SSM",
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/mc-{stack_suffix}/orchestrator-runtime-arn",
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/mc-{stack_suffix}/gateway-url",
                ],
            )
        )

        # ── Shared environment ─────────────────────────────────────
        shared_env = {
            "CONFIG_BUCKET": config_bucket.bucket_name,
            "RESULTS_BUCKET": results_bucket.bucket_name,
            "JOBS_TABLE_NAME": jobs_table.table_name,
            "MODEL_ID": model_id,
            "MAX_TOKENS": str(max_tokens),
            "LOG_LEVEL": "INFO",
            "GLOSSARY_KB_ID": glossary_kb_id,
            # Inference profile ARNs for cost tracking
            "SONNET_46_PROFILE_ARN": sonnet_46_profile_arn,
            "OPUS_46_PROFILE_ARN": opus_46_profile_arn,
            "SONNET_45_PROFILE_ARN": sonnet_45_profile_arn,
            "HAIKU_45_PROFILE_ARN": haiku_45_profile_arn,
        }

        # ── Lambda Powertools layer (AWS-managed, no build required) ──
        powertools_layer = lambda_.LayerVersion.from_layer_version_arn(
            self,
            "PowertoolsLayer",
            f"arn:aws:lambda:{self.region}:017000801446:layer:AWSLambdaPowertoolsPythonV3-python313-x86_64:33",
        )

        # ── Shared DLQ for all specialist functions ────────────────
        self.specialist_dlq = sqs.Queue(
            self,
            "SpecialistDLQ",
            queue_name=f"media-contracts-specialist-dlq-{deployment_id}-{stack_suffix}",
            retention_period=Duration.days(14),
            encryption=sqs.QueueEncryption.KMS_MANAGED,
            enforce_ssl=True,
        )

        # ── Build the Lambda asset with shared deps bundled in ─────
        # The handler imports from utils/ and agentcore/shared/. CDK runs the
        # command below inside the Python 3.13 SAM build image so we get a
        # reproducible Lambda-Linux build. Docker must be running.
        specialist_code = lambda_.Code.from_asset(
            "..",
            bundling=BundlingOptions(
                image=lambda_.Runtime.PYTHON_3_13.bundling_image,
                command=[
                    "bash",
                    "-c",
                    (
                        "cp agentcore/specialist_lambda/handler.py /asset-output/ && "
                        "mkdir -p /asset-output/utils /asset-output/agentcore/shared && "
                        "cp -r utils/. /asset-output/utils/ && "
                        "cp -r agentcore/shared/. /asset-output/agentcore/shared/ && "
                        "touch /asset-output/agentcore/__init__.py"
                    ),
                ],
            ),
        )

        # ── Create one Lambda per specialist ───────────────────────
        self.functions: dict[str, lambda_.Function] = {}

        for specialist in SPECIALISTS:
            specialist_log_group = logs.LogGroup(
                self,
                f"{specialist.title().replace('_', '')}Logs",
                log_group_name=f"/aws/lambda/media-contracts-specialist-{specialist.replace('_', '-')}-{deployment_id}-{stack_suffix}",
                retention=logs.RetentionDays.ONE_YEAR,
            )

            fn = lambda_.Function(
                self,
                f"{specialist.title().replace('_', '')}Lambda",
                function_name=f"media-contracts-specialist-{specialist.replace('_', '-')}-{deployment_id}-{stack_suffix}",
                runtime=lambda_.Runtime.PYTHON_3_13,
                handler="handler.lambda_handler",
                code=specialist_code,
                role=self.lambda_role,
                timeout=Duration.minutes(14),  # just under Lambda 15-min max
                memory_size=1024,
                reserved_concurrent_executions=10,  # prevent starving account concurrency
                dead_letter_queue=self.specialist_dlq,
                layers=[powertools_layer],
                tracing=lambda_.Tracing.ACTIVE,
                log_group=specialist_log_group,
                environment={
                    **shared_env,
                    "SPECIALIST_NAME": specialist,
                    "POWERTOOLS_SERVICE_NAME": f"media-contracts-{specialist}",
                    "POWERTOOLS_LOG_LEVEL": "INFO",
                },
            )
            self.functions[specialist] = fn

            CfnOutput(
                self,
                f"{specialist.title().replace('_', '')}FunctionArn",
                value=fn.function_arn,
                export_name=f"{self.stack_name}-{specialist.replace('_', '-')}-FunctionArn",
            )

        # ── CDK Nag suppressions ───────────────────────────────────

        # Helper to get the CloudFormation logical ID for cross-stack L2 constructs
        def _logical_id(construct) -> str:
            return Stack.of(construct).get_logical_id(construct.node.default_child)

        _config_id = _logical_id(config_bucket)
        _results_id = _logical_id(results_bucket)

        # IAM5: SpecialistLambdaRole default policy contains wildcards that
        # cdk-nag flags. Each is either required by the AWS API (no resource-level
        # support) or prefix-scoped to a known path with dynamic object keys.
        NagSuppressions.add_resource_suppressions(
            self.lambda_role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "xray:PutTraceSegments, xray:PutTelemetryRecords, "
                    "xray:GetSamplingRules, xray:GetSamplingTargets "
                    "have no resource-level support — wildcard required per AWS docs.",
                    "appliesTo": ["Resource::*"],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "S3 prompt paths use prefix-scoped wildcards — individual "
                    "object keys are XML/JSON files discovered at runtime via ListObjects.",
                    "appliesTo": [
                        f"Resource::<{_config_id}.Arn>/prompts/foundation/*",
                        f"Resource::<{_config_id}.Arn>/prompts/agents/*",
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "S3 results paths use prefix-scoped wildcards with dynamic "
                    "job IDs that cannot be enumerated at deploy time.",
                    "appliesTo": [
                        f"Resource::<{_results_id}.Arn>/jobs-canonical-versions/*/specialists/{specialist}.xml"
                        for specialist in SPECIALISTS
                    ]
                    + [
                        f"Resource::<{_results_id}.Arn>/jobs-canonical-versions/*/specialists/{specialist}.xml.metadata.json"
                        for specialist in SPECIALISTS
                    ]
                    + [
                        f"Resource::<{_results_id}.Arn>/jobs-kb-versions/*/specialists/{specialist}.txt"
                        for specialist in SPECIALISTS
                    ]
                    + [
                        f"Resource::<{_results_id}.Arn>/jobs-kb-versions/*/specialists/{specialist}.txt.metadata.json"
                        for specialist in SPECIALISTS
                    ]
                    + [
                        f"Resource::<{_results_id}.Arn>/jobs-canonical-versions/*/extraction/*",
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "Bedrock cross-region inference requires region wildcard in "
                    "model ARNs — scoped to specific named foundation models.",
                    "appliesTo": [
                        "Resource::arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6",
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "CloudWatch Logs log group ARNs include :* suffix for log "
                    "streams — scoped to specific specialist Lambda log group prefixes.",
                    "appliesTo": [
                        f"Resource::arn:aws:logs:{self.region}:<AWS::AccountId>:log-group:/aws/lambda/"
                        f"media-contracts-specialist-{specialist.replace('_', '-')}-{deployment_id}-{stack_suffix}:*"
                        for specialist in SPECIALISTS
                    ],
                },
            ],
            apply_to_children=True,
        )

        # L1 only: we're on Python 3.13 — the latest runtime with a published
        # AWS Lambda Powertools layer. 3.14 is not yet supported by Powertools.
        for specialist in SPECIALISTS:
            NagSuppressions.add_resource_suppressions(
                self.functions[specialist],
                [
                    {
                        "id": "AwsSolutions-L1",
                        "reason": "Python 3.13 is the latest runtime supported by the AWS Lambda Powertools managed layer (AWSLambdaPowertoolsPythonV3-python313-x86_64); 3.14 not yet available.",
                    },
                ],
            )

    def _apply_common_tags(self) -> None:
        for k, v in self.deployment_tags.items():
            Tags.of(self).add(k, v)
