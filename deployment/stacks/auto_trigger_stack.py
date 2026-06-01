"""Auto-Trigger Stack for MediaContracts.

Creates a Lambda function that fires when a PDF is uploaded to
source-bucket/pipeline/ and automatically starts the pipeline.

S3 event: s3:ObjectCreated:* on prefix=pipeline/, suffix=.pdf
"""

from aws_cdk import (
    Duration,
    Stack,
    Tags,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
    aws_dynamodb as dynamodb,
)
from constructs import Construct
from cdk_nag import NagSuppressions


class AutoTriggerStack(Stack):
    """Lambda + S3 event notification for pipeline/ prefix auto-trigger."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        deployment_id: str,
        stack_suffix: str,
        deployment_tags: dict[str, str],
        source_bucket_name: str,
        source_bucket_arn: str,
        jobs_table: dynamodb.Table,
        orchestrator_runtime_arn: str,
        kms_key_arn: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.deployment_id = deployment_id
        self.deployment_tags = deployment_tags
        self._apply_common_tags()

        # Import bucket by name to avoid cross-stack cyclic reference
        source_bucket = s3.Bucket.from_bucket_attributes(
            self,
            "SourceBucket",
            bucket_name=source_bucket_name,
            bucket_arn=source_bucket_arn,
        )

        # ── Execution role ─────────────────────────────────────────
        role = iam.Role(
            self,
            "AutoTriggerRole",
            role_name=f"media-contracts-auto-trigger-{deployment_id}-{stack_suffix}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description="Execution role for MediaContracts auto-trigger Lambda",
        )

        # CloudWatch Logs
        role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudWatchLogs",
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=[
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/lambda/media-contracts-auto-trigger-*-{stack_suffix}"
                ],
            )
        )

        # SSM — read orchestrator runtime ARN
        role.add_to_policy(
            iam.PolicyStatement(
                sid="SSMRead",
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/mc-{stack_suffix}/*"
                ],
            )
        )

        # AgentCore — invoke orchestrator runtime
        role.add_to_policy(
            iam.PolicyStatement(
                sid="InvokeRuntime",
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=[orchestrator_runtime_arn],
            )
        )

        # DynamoDB — write PENDING record
        jobs_table.grant_write_data(role)

        # KMS — decrypt S3 event metadata (not object content, but needed for table writes)
        role.add_to_policy(
            iam.PolicyStatement(
                sid="KMS",
                actions=["kms:Decrypt", "kms:GenerateDataKey"],
                resources=[kms_key_arn],
            )
        )

        # ── Log group ──────────────────────────────────────────────
        log_group = logs.LogGroup(
            self,
            "AutoTriggerLogs",
            log_group_name=f"/aws/lambda/media-contracts-auto-trigger-{deployment_id}-{stack_suffix}",
            retention=logs.RetentionDays.ONE_YEAR,
        )

        # ── Lambda ─────────────────────────────────────────────────
        self.function = lambda_.Function(
            self,
            "AutoTriggerFn",
            function_name=f"media-contracts-auto-trigger-{deployment_id}-{stack_suffix}",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("../agentcore/auto_trigger"),
            role=role,
            timeout=Duration.seconds(30),
            memory_size=256,
            environment={
                "JOBS_TABLE_NAME": jobs_table.table_name,
                "LOG_LEVEL": "INFO",
            },
            tracing=lambda_.Tracing.ACTIVE,
            log_group=log_group,
        )

        # ── S3 event notification — pipeline/ prefix ───────────────
        source_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(self.function),
            s3.NotificationKeyFilter(prefix="pipeline/", suffix=".pdf"),
        )

        # ── cdk-nag suppressions ───────────────────────────────────
        # Helper to get the CloudFormation logical ID for L2 constructs
        def _logical_id(construct) -> str:
            return Stack.of(construct).get_logical_id(construct.node.default_child)

        _jobs_id = _logical_id(jobs_table)

        NagSuppressions.add_resource_suppressions(
            role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "CloudWatch Logs resource uses suffix wildcard for log stream names — "
                    "scoped to the specific Lambda log group prefix.",
                    "appliesTo": [
                        f"Resource::arn:aws:logs:{self.region}:<AWS::AccountId>:log-group:"
                        f"/aws/lambda/media-contracts-auto-trigger-*-{stack_suffix}"
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "SSM parameter path uses prefix wildcard — scoped to /mc-{stack_suffix}/.",
                    "appliesTo": [
                        f"Resource::arn:aws:ssm:{self.region}:<AWS::AccountId>:parameter/mc-{stack_suffix}/*"
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "CDK grant_write_data() adds /index/* for GSI access on the jobs table.",
                    "appliesTo": [f"Resource::<{_jobs_id}.Arn>/index/*"],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "X-Ray actions have no resource-level support — wildcard required.",
                    "appliesTo": ["Resource::*"],
                },
            ],
            apply_to_children=True,
        )

        NagSuppressions.add_stack_suppressions(
            self,
            [
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": "BucketNotificationsHandler is a CDK framework construct — "
                    "its managed policy cannot be overridden.",
                    "appliesTo": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
                    ],
                },
                {
                    "id": "AwsSolutions-L1",
                    "reason": "BucketNotificationsHandler is a CDK framework construct — "
                    "its Lambda runtime is managed by CDK and cannot be overridden. "
                    "AutoTriggerFn uses Python 3.13; 3.14 not yet validated for this use case.",
                },
            ],
        )

    def _apply_common_tags(self) -> None:
        for k, v in self.deployment_tags.items():
            Tags.of(self).add(k, v)
