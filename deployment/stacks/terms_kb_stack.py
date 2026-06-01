"""Terms Knowledge Base Stack for MediaContracts.

Creates a Bedrock Knowledge Base for glossary/terms definitions.
Backed by S3 Vectors (same pattern as the contract analysis KB).
The terms_bucket is the data source — pre-processed glossary .txt files
with .metadata.json sidecars are ingested here.
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


class TermsKBStack(Stack):
    """Bedrock Knowledge Base for glossary/terms definitions with S3 Vectors backend."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        deployment_id: str,
        stack_suffix: str,
        deployment_tags: dict[str, str],
        terms_bucket: s3.Bucket,
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
            role_name=f"media-contracts-terms-kb-role-{deployment_id}-{stack_suffix}",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
            description="Execution role for MediaContracts Terms Knowledge Base",
        )

        # Read terms bucket — entire bucket is glossary data
        self.kb_role.add_to_policy(
            iam.PolicyStatement(
                sid="TermsKbRead",
                actions=["s3:GetObject"],
                resources=[f"{terms_bucket.bucket_arn}/*"],
            )
        )
        self.kb_role.add_to_policy(
            iam.PolicyStatement(
                sid="TermsKbList",
                actions=["s3:ListBucket"],
                resources=[terms_bucket.bucket_arn],
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
        vector_index_arn = (
            f"arn:aws:s3vectors:{self.region}:{self.account}:bucket/"
            f"media-contracts-terms-vectors-{deployment_id}-{stack_suffix}/index/terms"
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
            vector_bucket_name=f"media-contracts-terms-vectors-{deployment_id}-{stack_suffix}",
        )
        vector_index = s3vectors.CfnIndex(
            self,
            "VectorIndex",
            vector_bucket_name=vector_bucket.vector_bucket_name,
            index_name="terms",
            data_type="float32",
            dimension=1024,  # Titan Embed v2 output dimension
            distance_metric="cosine",
        )
        vector_index.add_dependency(vector_bucket)

        # ── Log group for KB ingestion activity ────────────────────
        self.log_group = logs.LogGroup(
            self,
            "KBLogGroup",
            log_group_name=f"/bedrock/knowledge-base/media-contracts-terms-kb-{deployment_id}-{stack_suffix}",
            retention=logs.RetentionDays.ONE_YEAR,
        )

        # ── Knowledge Base (S3 Vectors storage) ───────────────────
        self.knowledge_base = bedrock.CfnKnowledgeBase(
            self,
            "TermsKB",
            name=f"media-contracts-terms-kb-{deployment_id}-{stack_suffix}",
            description="Glossary definitions — broadcast, film/TV, music rights, ODRL, SAG-AFTRA, VFX, and more",
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
                    index_arn=f"arn:aws:s3vectors:{self.region}:{self.account}:bucket/media-contracts-terms-vectors-{deployment_id}-{stack_suffix}/index/terms",
                ),
            ),
        )
        # KB can't create until the index exists and role policies are attached.
        self.knowledge_base.add_dependency(vector_index)
        for child in self.kb_role.node.find_all():
            if isinstance(child, (iam.CfnPolicy, iam.CfnManagedPolicy)):
                self.knowledge_base.add_dependency(child)

        # ── Data source — terms bucket ─────────────────────────────
        self.data_source = bedrock.CfnDataSource(
            self,
            "TermsDataSource",
            name=f"terms-glossaries-{deployment_id}-{stack_suffix}",
            knowledge_base_id=self.knowledge_base.attr_knowledge_base_id,
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=terms_bucket.bucket_arn,
                ),
            ),
            vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
                chunking_configuration=bedrock.CfnDataSource.ChunkingConfigurationProperty(
                    chunking_strategy="NONE",
                ),
            ),
        )
        self.data_source.node.add_dependency(self.knowledge_base)

        # ── SSM parameter for runtime discovery ───────────────────
        ssm.StringParameter(
            self,
            "TermsKBIdParam",
            parameter_name=f"/mc-{stack_suffix}/terms-kb-id",
            string_value=self.knowledge_base.attr_knowledge_base_id,
            description="Terms KB ID for glossary lookups",
        )

        # ── CDK Nag suppressions ───────────────────────────────────
        # Helper to get the CloudFormation logical ID for L2 constructs
        def _logical_id(construct) -> str:
            return Stack.of(construct).get_logical_id(construct.node.default_child)

        _terms_id = _logical_id(terms_bucket)

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
                        "Terms KB reads all objects in the terms bucket — the entire bucket "
                        "is the glossary data source, so /* is the correct scope."
                    ),
                    "appliesTo": [f"Resource::<{_terms_id}.Arn>/*"],
                },
            ],
            apply_to_children=True,
        )

        # ── Outputs ────────────────────────────────────────────────
        CfnOutput(
            self,
            "TermsKBId",
            value=self.knowledge_base.attr_knowledge_base_id,
            export_name=f"{self.stack_name}-TermsKBId",
        )
        CfnOutput(
            self,
            "TermsKBArn",
            value=self.knowledge_base.attr_knowledge_base_arn,
            export_name=f"{self.stack_name}-TermsKBArn",
        )
        CfnOutput(
            self,
            "TermsDataSourceId",
            value=self.data_source.attr_data_source_id,
            export_name=f"{self.stack_name}-TermsDataSourceId",
        )

    def _apply_common_tags(self) -> None:
        for k, v in self.deployment_tags.items():
            Tags.of(self).add(k, v)
