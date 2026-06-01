"""S3 Stack for MediaContracts.

Creates:
  - config_bucket  : versioned bucket for prompts (foundation + agent XML files)
  - source_bucket  : PDF contract uploads
  - results_bucket : specialist XML outputs, risk synthesis, summaries
                     (ingested into Bedrock KB backed by S3 Vectors)
"""

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    Tags,
    CfnOutput,
    aws_iam as iam,
    aws_kms as kms,
    aws_s3 as s3,
    aws_ssm as ssm,
)
from constructs import Construct
from cdk_nag import NagSuppressions


class S3Stack(Stack):
    """S3 buckets for MediaContracts pipeline."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        deployment_id: str,
        stack_suffix: str,
        deployment_tags: dict[str, str],
        cors_origin: str = "",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.deployment_id = deployment_id
        self.deployment_tags = deployment_tags
        self._apply_common_tags()

        prefix = "media-contracts"

        # ── KMS key shared across all buckets ──────────────────────
        self.kms_key = kms.Key(
            self,
            "S3KmsKey",
            alias=f"alias/{prefix}-s3-{deployment_id}-{stack_suffix}",
            description="KMS key for MediaContracts S3 buckets",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.RETAIN,  # never destroy — losing this destroys all encrypted data
        )

        # Allow CloudWatch Logs to use the key for encrypting log groups that
        # other stacks create (e.g. AgentCore runtime app/usage logs).
        # Scoped to log groups in this account/region via EncryptionContext.
        self.kms_key.add_to_resource_policy(
            iam.PolicyStatement(
                sid="AllowCloudWatchLogs",
                effect=iam.Effect.ALLOW,
                principals=[iam.ServicePrincipal(f"logs.{self.region}.amazonaws.com")],
                actions=[
                    "kms:Encrypt*",
                    "kms:Decrypt*",
                    "kms:ReEncrypt*",
                    "kms:GenerateDataKey*",
                    "kms:Describe*",
                ],
                resources=["*"],
                conditions={
                    "ArnLike": {
                        "kms:EncryptionContext:aws:logs:arn": (
                            f"arn:aws:logs:{self.region}:{self.account}:log-group:*"
                        )
                    }
                },
            )
        )

        # ── Access logging bucket ──────────────────────────────────
        # Receives server access logs from all three data buckets.
        # Uses S3-managed encryption (SSE-S3) — logging buckets cannot use KMS.
        self.logging_bucket = s3.Bucket(
            self,
            "LoggingBucket",
            bucket_name=f"{prefix}-access-logs-{deployment_id}-{stack_suffix}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # ── Config bucket — prompts live here ──────────────────────
        # Versioning enabled so prompt rollback = S3 version restore
        self.config_bucket = s3.Bucket(
            self,
            "ConfigBucket",
            bucket_name=f"{prefix}-config-{deployment_id}-{stack_suffix}",
            versioned=True,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.kms_key,
            bucket_key_enabled=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            server_access_logs_bucket=self.logging_bucket,
            server_access_logs_prefix="config/",
        )

        # ── Source bucket — PDF contract uploads ───────────────────
        source_cors = (
            [
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.PUT],
                    allowed_origins=[cors_origin],
                    allowed_headers=["*"],
                    max_age=900,
                )
            ]
            if cors_origin
            else None
        )

        self.source_bucket = s3.Bucket(
            self,
            "SourceBucket",
            bucket_name=f"{prefix}-source-{deployment_id}-{stack_suffix}",
            versioned=True,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.kms_key,
            bucket_key_enabled=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            server_access_logs_bucket=self.logging_bucket,
            server_access_logs_prefix="source/",
            cors=source_cors,
        )

        # ── Results bucket — pipeline outputs + KB data source ─────
        # Lifecycle: expire temp/ prefix after 1 day
        self.results_bucket = s3.Bucket(
            self,
            "ResultsBucket",
            bucket_name=f"{prefix}-results-{deployment_id}-{stack_suffix}",
            versioned=True,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.kms_key,
            bucket_key_enabled=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            server_access_logs_bucket=self.logging_bucket,
            server_access_logs_prefix="results/",
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="ExpireTempObjects",
                    prefix="temp/",
                    expiration=Duration.days(1),
                    noncurrent_version_expiration=Duration.days(1),
                )
            ],
        )

        # ── Terms bucket — glossary definitions for Terms KB ────────
        self.terms_bucket = s3.Bucket(
            self,
            "TermsBucket",
            bucket_name=f"{prefix}-terms-{deployment_id}-{stack_suffix}",
            versioned=True,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.kms_key,
            bucket_key_enabled=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            server_access_logs_bucket=self.logging_bucket,
            server_access_logs_prefix="terms/",
        )

        # ── CDK Nag suppressions ───────────────────────────────────
        # Logging bucket itself does not need access logs (standard practice)
        NagSuppressions.add_resource_suppressions(
            self.logging_bucket,
            [
                {
                    "id": "AwsSolutions-S1",
                    "reason": "This IS the access logging bucket — self-logging is not required.",
                }
            ],
        )

        NagSuppressions.add_stack_suppressions(
            self,
            [
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": (
                        "CustomS3AutoDeleteObjectsCustomResourceProvider is a CDK framework "
                        "construct — its managed policy cannot be overridden."
                    ),
                    "appliesTo": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
                    ],
                },
                {
                    "id": "AwsSolutions-L1",
                    "reason": (
                        "CustomS3AutoDeleteObjectsCustomResourceProvider is a CDK framework "
                        "construct — its Lambda runtime is managed by CDK and cannot be overridden."
                    ),
                },
            ],
        )

        # ── SSM parameters for runtime discovery ───────────────────
        ssm.StringParameter(
            self,
            "ConfigBucketParam",
            parameter_name=f"/mc-{stack_suffix}/config-bucket-name",
            string_value=self.config_bucket.bucket_name,
            description="Config bucket name for prompt loading",
        )

        ssm.StringParameter(
            self,
            "ResultsBucketParam",
            parameter_name=f"/mc-{stack_suffix}/results-bucket-name",
            string_value=self.results_bucket.bucket_name,
            description="Results bucket name for pipeline outputs",
        )

        ssm.StringParameter(
            self,
            "SourceBucketParam",
            parameter_name=f"/mc-{stack_suffix}/source-bucket-name",
            string_value=self.source_bucket.bucket_name,
            description="Source bucket name for PDF contract uploads",
        )

        ssm.StringParameter(
            self,
            "TermsBucketParam",
            parameter_name=f"/mc-{stack_suffix}/terms-bucket-name",
            string_value=self.terms_bucket.bucket_name,
            description="Terms bucket name for glossary definitions (Terms KB data source)",
        )

        # ── Outputs ────────────────────────────────────────────────
        CfnOutput(
            self,
            "ConfigBucketName",
            value=self.config_bucket.bucket_name,
            export_name=f"{self.stack_name}-ConfigBucketName",
        )
        CfnOutput(
            self,
            "ConfigBucketArn",
            value=self.config_bucket.bucket_arn,
            export_name=f"{self.stack_name}-ConfigBucketArn",
        )
        CfnOutput(
            self,
            "SourceBucketName",
            value=self.source_bucket.bucket_name,
            export_name=f"{self.stack_name}-SourceBucketName",
        )
        CfnOutput(
            self,
            "ResultsBucketName",
            value=self.results_bucket.bucket_name,
            export_name=f"{self.stack_name}-ResultsBucketName",
        )
        CfnOutput(
            self,
            "ResultsBucketArn",
            value=self.results_bucket.bucket_arn,
            export_name=f"{self.stack_name}-ResultsBucketArn",
        )
        CfnOutput(
            self,
            "TermsBucketName",
            value=self.terms_bucket.bucket_name,
            export_name=f"{self.stack_name}-TermsBucketName",
        )
        CfnOutput(
            self,
            "TermsBucketArn",
            value=self.terms_bucket.bucket_arn,
            export_name=f"{self.stack_name}-TermsBucketArn",
        )
        CfnOutput(
            self,
            "KmsKeyArn",
            value=self.kms_key.key_arn,
            export_name=f"{self.stack_name}-KmsKeyArn",
        )

    def _apply_common_tags(self) -> None:
        for k, v in self.deployment_tags.items():
            Tags.of(self).add(k, v)
