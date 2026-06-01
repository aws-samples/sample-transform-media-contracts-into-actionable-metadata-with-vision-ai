"""KB Sync Stack for MediaContracts.

Creates Lambda functions that trigger Bedrock KB ingestion when
files land in the relevant S3 buckets:
  - results bucket (jobs-kb-versions/ prefix) → Contract Analysis KB
  - terms bucket (any object created) → Terms KB
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
)
from constructs import Construct
from cdk_nag import NagSuppressions


class KBSyncStack(Stack):
    """Lambda + S3 event notifications for KB ingestion sync."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        deployment_id: str,
        stack_suffix: str,
        deployment_tags: dict[str, str],
        results_bucket_name: str,
        results_bucket_arn: str,
        terms_bucket_name: str,
        terms_bucket_arn: str,
        contract_kb_id: str,
        contract_datasource_id: str,
        terms_kb_id: str,
        terms_datasource_id: str,
        kms_key_arn: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.deployment_id = deployment_id
        self.deployment_tags = deployment_tags
        self._apply_common_tags()

        # Import buckets by name to avoid cross-stack cyclic references
        results_bucket = s3.Bucket.from_bucket_attributes(
            self,
            "ResultsBucket",
            bucket_name=results_bucket_name,
            bucket_arn=results_bucket_arn,
        )
        terms_bucket = s3.Bucket.from_bucket_attributes(
            self,
            "TermsBucket",
            bucket_name=terms_bucket_name,
            bucket_arn=terms_bucket_arn,
        )

        # KB ARNs for IAM scoping
        contract_kb_arn = f"arn:aws:bedrock:{self.region}:{self.account}:knowledge-base/{contract_kb_id}"
        terms_kb_arn = (
            f"arn:aws:bedrock:{self.region}:{self.account}:knowledge-base/{terms_kb_id}"
        )

        # ── Shared execution role ────────────────────────────────────
        role = iam.Role(
            self,
            "KBSyncRole",
            role_name=f"media-contracts-kb-sync-{deployment_id}-{stack_suffix}",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description="Execution role for MediaContracts KB sync Lambdas",
        )

        role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudWatchLogs",
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=[
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/lambda/media-contracts-kb-sync-*-{stack_suffix}"
                ],
            )
        )

        role.add_to_policy(
            iam.PolicyStatement(
                sid="StartIngestion",
                actions=["bedrock-agent:StartIngestionJob"],
                resources=[contract_kb_arn, terms_kb_arn],
            )
        )

        role.add_to_policy(
            iam.PolicyStatement(
                sid="KMS",
                actions=["kms:Decrypt"],
                resources=[kms_key_arn],
            )
        )

        # ── Contract Analysis KB sync Lambda ─────────────────────────
        contract_log_group = logs.LogGroup(
            self,
            "ContractSyncLogs",
            log_group_name=f"/aws/lambda/media-contracts-kb-sync-contract-{deployment_id}-{stack_suffix}",
            retention=logs.RetentionDays.ONE_YEAR,
        )

        self.contract_sync_fn = lambda_.Function(
            self,
            "ContractSyncFn",
            function_name=f"media-contracts-kb-sync-contract-{deployment_id}-{stack_suffix}",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("../agentcore/kb_sync"),
            role=role,
            timeout=Duration.seconds(30),
            memory_size=128,
            environment={
                "KB_ID": contract_kb_id,
                "DATA_SOURCE_ID": contract_datasource_id,
                "LOG_LEVEL": "INFO",
            },
            tracing=lambda_.Tracing.ACTIVE,
            log_group=contract_log_group,
        )

        # S3 event: results bucket, jobs-kb-versions/ prefix
        results_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(self.contract_sync_fn),
            s3.NotificationKeyFilter(prefix="jobs-kb-versions/"),
        )

        # ── Terms KB sync Lambda ─────────────────────────────────────
        terms_log_group = logs.LogGroup(
            self,
            "TermsSyncLogs",
            log_group_name=f"/aws/lambda/media-contracts-kb-sync-terms-{deployment_id}-{stack_suffix}",
            retention=logs.RetentionDays.ONE_YEAR,
        )

        self.terms_sync_fn = lambda_.Function(
            self,
            "TermsSyncFn",
            function_name=f"media-contracts-kb-sync-terms-{deployment_id}-{stack_suffix}",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("../agentcore/kb_sync"),
            role=role,
            timeout=Duration.seconds(30),
            memory_size=128,
            environment={
                "KB_ID": terms_kb_id,
                "DATA_SOURCE_ID": terms_datasource_id,
                "LOG_LEVEL": "INFO",
            },
            tracing=lambda_.Tracing.ACTIVE,
            log_group=terms_log_group,
        )

        # S3 event: terms bucket, any object
        terms_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(self.terms_sync_fn),
        )

        # ── cdk-nag suppressions ─────────────────────────────────────
        NagSuppressions.add_resource_suppressions(
            role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "CloudWatch Logs resource uses suffix wildcard — scoped to "
                    "the specific KB sync Lambda log group prefix.",
                    "appliesTo": [
                        f"Resource::arn:aws:logs:{self.region}:<AWS::AccountId>:log-group:"
                        f"/aws/lambda/media-contracts-kb-sync-*-{stack_suffix}"
                    ],
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
                    "User-authored functions (ContractSyncFn, TermsSyncFn) use Python 3.13; "
                    "3.14 not yet validated for this use case.",
                },
            ],
        )

    def _apply_common_tags(self) -> None:
        for k, v in self.deployment_tags.items():
            Tags.of(self).add(k, v)
