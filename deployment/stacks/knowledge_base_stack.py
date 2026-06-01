"""Knowledge Base Stack for MediaContracts.

Creates a Bedrock Knowledge Base backed by S3 Vectors (not OSS).
The results_bucket is the data source — specialist XML outputs and
summaries are ingested here after each pipeline run.

S3 Vectors is chosen over OSS because:
  - ~90% cheaper at bulk scale
  - Serverless, no OCU billing
  - Sub-second query latency is acceptable for KB Chat use case
  - RetrieveAndGenerate API is identical regardless of backend
"""

from aws_cdk import (
    Stack,
    Tags,
    CfnOutput,
    aws_bedrock as bedrock,
    aws_iam as iam,
    aws_logs as logs,
    aws_s3 as s3,
    aws_s3vectors as s3vectors,
    aws_ssm as ssm,
)
from constructs import Construct
from cdk_nag import NagSuppressions


# Titan Embeddings V2 — 1024 dimensions, supported by S3 Vectors
EMBEDDING_MODEL_ARN = (
    "arn:aws:bedrock:us-west-2::foundation-model/amazon.titan-embed-text-v2:0"
)


class KnowledgeBaseStack(Stack):
    """Bedrock Knowledge Base with S3 Vectors backend."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        deployment_id: str,
        stack_suffix: str,
        deployment_tags: dict[str, str],
        results_bucket: s3.Bucket,
        kms_key_arn: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.deployment_id = deployment_id
        self.deployment_tags = deployment_tags
        self._apply_common_tags()

        # ── KB execution role ──────────────────────────────────────
        self.kb_role = iam.Role(
            self,
            "KBRole",
            role_name=f"media-contracts-kb-role-{deployment_id}-{stack_suffix}",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
            description="Execution role for MediaContracts Bedrock Knowledge Base",
        )

        # Read results bucket — scoped to the KB data source prefix only
        self.kb_role.add_to_policy(
            iam.PolicyStatement(
                sid="ResultsKbRead",
                actions=["s3:GetObject"],
                resources=[f"{results_bucket.bucket_arn}/jobs-kb-versions/*"],
            )
        )
        self.kb_role.add_to_policy(
            iam.PolicyStatement(
                sid="ResultsKbList",
                actions=["s3:ListBucket"],
                resources=[results_bucket.bucket_arn],
                conditions={"StringLike": {"s3:prefix": ["jobs-kb-versions/*"]}},
            )
        )

        # KMS decrypt for reading encrypted objects
        self.kb_role.add_to_policy(
            iam.PolicyStatement(
                sid="KMSDecrypt",
                actions=["kms:Decrypt", "kms:GenerateDataKey"],
                resources=[kms_key_arn],
            )
        )

        # Bedrock embedding model invocation
        self.kb_role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockEmbeddings",
                actions=["bedrock:InvokeModel"],
                resources=[EMBEDDING_MODEL_ARN],
            )
        )

        # S3 Vectors — permissions required by the Bedrock KB service role.
        # Per https://docs.aws.amazon.com/bedrock/latest/userguide/kb-permissions.html
        # Bedrock KB requires exactly these five actions on the specific index ARN.
        vector_index_arn = (
            f"arn:aws:s3vectors:{self.region}:{self.account}:bucket/"
            f"media-contracts-vectors-{deployment_id}-{stack_suffix}/index/contracts"
        )
        self.kb_role.add_to_policy(
            iam.PolicyStatement(
                sid="S3VectorIndexReadWrite",
                actions=[
                    "s3vectors:PutVectors",
                    "s3vectors:GetVectors",
                    "s3vectors:DeleteVectors",
                    "s3vectors:QueryVectors",
                    "s3vectors:GetIndex",
                ],
                resources=[vector_index_arn],
            )
        )
        # ListVectorBuckets has no resource-level support — must be *
        self.kb_role.add_to_policy(
            iam.PolicyStatement(
                sid="S3VectorsListBuckets",
                actions=["s3vectors:ListVectorBuckets"],
                resources=["*"],
            )
        )

        # ── S3 Vectors bucket + index (storage backend for the KB) ─
        vector_bucket = s3vectors.CfnVectorBucket(
            self,
            "VectorBucket",
            vector_bucket_name=f"media-contracts-vectors-{deployment_id}-{stack_suffix}",
        )
        vector_index = s3vectors.CfnIndex(
            self,
            "VectorIndex",
            vector_bucket_name=vector_bucket.vector_bucket_name,
            index_name="contracts",
            data_type="float32",
            dimension=1024,  # Titan Embed v2 output dimension
            distance_metric="cosine",
        )
        vector_index.add_dependency(vector_bucket)

        # ── Log group for KB ingestion activity ────────────────────
        self.log_group = logs.LogGroup(
            self,
            "KBLogGroup",
            log_group_name=f"/bedrock/knowledge-base/media-contracts-kb-{deployment_id}-{stack_suffix}",
            retention=logs.RetentionDays.ONE_YEAR,
        )

        # ── Knowledge Base (S3 Vectors storage) ───────────────────
        self.knowledge_base = bedrock.CfnKnowledgeBase(
            self,
            "ContractKB",
            name=f"media-contracts-kb-{deployment_id}-{stack_suffix}",
            description="Contract analysis results - specialist outputs, risk synthesis, summaries",
            role_arn=self.kb_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=EMBEDDING_MODEL_ARN,
                ),
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="S3_VECTORS",
                s3_vectors_configuration=bedrock.CfnKnowledgeBase.S3VectorsConfigurationProperty(
                    index_arn=f"arn:aws:s3vectors:{self.region}:{self.account}:bucket/media-contracts-vectors-{deployment_id}-{stack_suffix}/index/contracts",
                ),
            ),
        )
        # KB can't create until the index exists, the role policies are attached,
        # and the vector bucket is ready. Bedrock KB assumes the role immediately
        # after creation to validate the index — if the policy isn't attached yet,
        # the validation fails with a 403 on s3vectors:QueryVectors.
        self.knowledge_base.add_dependency(vector_index)
        for child in self.kb_role.node.find_all():
            if isinstance(child, (iam.CfnPolicy, iam.CfnManagedPolicy)):
                self.knowledge_base.add_dependency(child)

        # ── Data source — results bucket ───────────────────────────
        self.data_source = bedrock.CfnDataSource(
            self,
            "ResultsDataSource",
            name=f"contract-results-{deployment_id}-{stack_suffix}",
            knowledge_base_id=self.knowledge_base.attr_knowledge_base_id,
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=results_bucket.bucket_arn,
                    inclusion_prefixes=["jobs-kb-versions/"],
                ),
            ),
            vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
                chunking_configuration=bedrock.CfnDataSource.ChunkingConfigurationProperty(
                    chunking_strategy="FIXED_SIZE",
                    fixed_size_chunking_configuration=bedrock.CfnDataSource.FixedSizeChunkingConfigurationProperty(
                        max_tokens=512,
                        overlap_percentage=20,
                    ),
                ),
            ),
        )

        self.data_source.node.add_dependency(self.knowledge_base)

        # ── SSM parameter for runtime discovery ───────────────────
        ssm.StringParameter(
            self,
            "ContractKBIdParam",
            parameter_name=f"/mc-{stack_suffix}/contract-kb-id",
            string_value=self.knowledge_base.attr_knowledge_base_id,
            description="Contract Analysis KB ID for UI and specialist lookups",
        )

        # ── CDK Nag suppressions ───────────────────────────────────
        # Helper to get the CloudFormation logical ID for L2 constructs
        def _logical_id(construct) -> str:
            return Stack.of(construct).get_logical_id(construct.node.default_child)

        _results_id = _logical_id(results_bucket)

        NagSuppressions.add_resource_suppressions(
            self.kb_role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "s3vectors:ListVectorBuckets has no resource-level support — wildcard required by the service.",
                    "appliesTo": ["Resource::*"],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "S3 GetObject uses prefix-scoped wildcard /jobs-kb-versions/* — "
                        "individual object keys are dynamic job IDs."
                    ),
                    "appliesTo": [f"Resource::<{_results_id}.Arn>/jobs-kb-versions/*"],
                },
            ],
            apply_to_children=True,
        )

        # ── Outputs ────────────────────────────────────────────────
        CfnOutput(
            self,
            "KnowledgeBaseId",
            value=self.knowledge_base.attr_knowledge_base_id,
            export_name=f"{self.stack_name}-KnowledgeBaseId",
        )
        CfnOutput(
            self,
            "KnowledgeBaseArn",
            value=self.knowledge_base.attr_knowledge_base_arn,
            export_name=f"{self.stack_name}-KnowledgeBaseArn",
        )
        CfnOutput(
            self,
            "DataSourceId",
            value=self.data_source.attr_data_source_id,
            export_name=f"{self.stack_name}-DataSourceId",
        )
        CfnOutput(
            self,
            "KBRoleArn",
            value=self.kb_role.role_arn,
            export_name=f"{self.stack_name}-KBRoleArn",
        )

    def _apply_common_tags(self) -> None:
        for k, v in self.deployment_tags.items():
            Tags.of(self).add(k, v)
