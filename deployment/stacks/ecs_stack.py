"""ECS Stack for MediaContracts UI.

Defines the ECS Express Gateway Service with all environment variables sourced
from SSM Parameter Store via valueFrom references. No plaintext secrets
in the service definition or deploy scripts.

SSM parameters read at task startup:
  /media-contracts/orchestrator-runtime-arn  (written by AgentCoreRuntimesStack)
  /media-contracts/jobs-table-name           (written by DynamoDBStack)
  /media-contracts/config-bucket-name        (written by S3Stack)
  /media-contracts/results-bucket-name       (written by S3Stack)
  /media-contracts/source-bucket-name        (written by S3Stack)
  /media-contracts/chat-model                (written here, static)
  /media-contracts/agent-mode                (written here, static)
  /media-contracts/node-env                  (written here, static)
  /media-contracts/cognito-user-pool-id      (written by CognitoStack)
  /media-contracts/cognito-domain            (written by CognitoStack)

The ECS task execution role gets ssm:GetParameters on /media-contracts/*
so ECS can inject the values before the container starts.

The ECS task role gets:
  - bedrock-agentcore:InvokeAgentRuntime (call orchestrator)
  - dynamodb:Query on jobs table (progress polling)
  - bedrock-agent-runtime:RetrieveAndGenerate (KB chat)
  - bedrock:InvokeModel (chat endpoint)
  - s3:GetObject / s3:ListBucket on all three buckets

After the Express service is created, an AwsCustomResource updates the
Cognito UI client callback/logout URLs to point at the service endpoint.
"""

from aws_cdk import (
    Stack,
    Tags,
    CfnOutput,
    CfnTag,
    aws_ecs as ecs,
    aws_iam as iam,
    aws_logs as logs,
    aws_ssm as ssm,
    custom_resources as cr,
)
from constructs import Construct
from cdk_nag import NagSuppressions


class ECSStack(Stack):
    """ECS Express Gateway Service and IAM roles for the MediaContracts UI."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        deployment_id: str,
        stack_suffix: str,
        deployment_tags: dict[str, str],
        config_bucket_arn: str,
        results_bucket_arn: str,
        source_bucket_arn: str,
        jobs_table_arn: str,
        kms_key_arn: str,
        private_subnet_ids: list[str],
        ui_task_sg_id: str,
        cognito_user_pool_id: str,
        cognito_ui_client_id: str,
        image_tag: str = "latest",
        chat_model: str = "us.anthropic.claude-sonnet-4-6",
        agent_mode: str = "false",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.deployment_id = deployment_id
        self.deployment_tags = deployment_tags
        self._apply_common_tags()

        ssm_prefix = f"/mc-{stack_suffix}"

        # ── Static SSM parameters (created by this stack) ─────────
        chat_model_param = ssm.StringParameter(
            self,
            "ChatModelParam",
            parameter_name=f"{ssm_prefix}/chat-model",
            string_value=chat_model,
            description="Bedrock model ID for the chat endpoint",
        )
        agent_mode_param = ssm.StringParameter(
            self,
            "AgentModeParam",
            parameter_name=f"{ssm_prefix}/agent-mode",
            string_value=agent_mode,
            description="Lock agent mode on/off for all users (true/false)",
        )
        node_env_param = ssm.StringParameter(
            self,
            "NodeEnvParam",
            parameter_name=f"{ssm_prefix}/node-env",
            string_value="production",
            description="NODE_ENV for the UI container",
        )

        # ── Task execution role (ECS pulls images + injects SSM) ───
        self.exec_role = iam.Role(
            self,
            "TaskExecRole",
            role_name=f"media-contracts-ecs-task-exec-{deployment_id}-{stack_suffix}",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSTaskExecutionRolePolicy"
                )
            ],
        )

        # Allow ECS to read all /media-contracts/* SSM params at startup
        self.exec_role.add_to_policy(
            iam.PolicyStatement(
                sid="SSMGetParams",
                actions=["ssm:GetParameters", "ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/mc-{stack_suffix}/*"
                ],
            )
        )

        # ── Task role (what the running container can do) ──────────
        self.task_role = iam.Role(
            self,
            "TaskRole",
            role_name=f"media-contracts-ecs-task-role-{deployment_id}-{stack_suffix}",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            description="Runtime permissions for MediaContracts ECS UI container",
        )

        # Invoke orchestrator runtime
        self.task_role.add_to_policy(
            iam.PolicyStatement(
                sid="InvokeOrchestratorRuntime",
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=[
                    f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:runtime/*"
                ],
            )
        )

        # DynamoDB — query jobs table for progress polling + delete jobs from UI
        self.task_role.add_to_policy(
            iam.PolicyStatement(
                sid="DynamoDBJobsQuery",
                actions=["dynamodb:Query", "dynamodb:GetItem", "dynamodb:DeleteItem"],
                resources=[jobs_table_arn, f"{jobs_table_arn}/index/*"],
            )
        )

        # Bedrock — KB RetrieveAndGenerate + chat Converse
        self.task_role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockInvoke",
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                resources=[
                    "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6",
                    "arn:aws:bedrock:*::foundation-model/anthropic.claude-opus-4-6-v1",
                    "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0",
                    "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
                    "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v2:0",
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/us.anthropic.claude-sonnet-4-6",
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/us.anthropic.claude-opus-4-6-v1",
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0",
                ],
            )
        )
        self.task_role.add_to_policy(
            iam.PolicyStatement(
                sid="BedrockAgentRuntime",
                actions=[
                    "bedrock-agent-runtime:RetrieveAndGenerate",
                    "bedrock-agent-runtime:Retrieve",
                    "bedrock:RetrieveAndGenerate",
                    "bedrock:Retrieve",
                ],
                resources=["*"],  # bedrock-agent-runtime has no resource-level support
            )
        )

        # S3 — scoped per bucket to what the UI actually reads/lists.
        self.task_role.add_to_policy(
            iam.PolicyStatement(
                sid="S3ConfigRead",
                actions=["s3:GetObject"],
                resources=[f"{config_bucket_arn}/*"],
            )
        )
        self.task_role.add_to_policy(
            iam.PolicyStatement(
                sid="S3ConfigList",
                actions=["s3:ListBucket"],
                resources=[config_bucket_arn],
            )
        )

        self.task_role.add_to_policy(
            iam.PolicyStatement(
                sid="S3SourceRead",
                actions=["s3:GetObject"],
                resources=[f"{source_bucket_arn}/*"],
            )
        )
        self.task_role.add_to_policy(
            iam.PolicyStatement(
                sid="S3SourceList",
                actions=["s3:ListBucket"],
                resources=[source_bucket_arn],
            )
        )
        self.task_role.add_to_policy(
            iam.PolicyStatement(
                sid="S3ResultsRead",
                actions=["s3:GetObject"],
                resources=[f"{results_bucket_arn}/jobs-canonical-versions/*"],
            )
        )
        self.task_role.add_to_policy(
            iam.PolicyStatement(
                sid="S3ResultsList",
                actions=["s3:ListBucket"],
                resources=[results_bucket_arn],
                conditions={
                    "StringLike": {
                        "s3:prefix": [
                            "jobs-canonical-versions",
                            "jobs-canonical-versions/*",
                        ]
                    }
                },
            )
        )
        self.task_role.add_to_policy(
            iam.PolicyStatement(
                sid="S3UserUpload",
                actions=["s3:PutObject"],
                resources=[f"{source_bucket_arn}/testing/*"],
            )
        )

        # KMS — decrypt S3 objects, DynamoDB data, and encrypt uploads
        self.task_role.add_to_policy(
            iam.PolicyStatement(
                sid="KMSDecryptAndEncrypt",
                actions=["kms:Decrypt", "kms:DescribeKey", "kms:GenerateDataKey"],
                resources=[kms_key_arn],
            )
        )

        # SSM — read params at runtime (for any server-side lookups)
        self.task_role.add_to_policy(
            iam.PolicyStatement(
                sid="SSMReadParams",
                actions=["ssm:GetParameter", "ssm:GetParameters"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter/mc-{stack_suffix}/*"
                ],
            )
        )
        # ── Infrastructure role (ECS manages ALB + networking) ─────
        self.infra_role = iam.Role(
            self,
            "InfraRole",
            role_name=f"media-contracts-ecs-infra-{deployment_id}-{stack_suffix}",
            assumed_by=iam.ServicePrincipal("ecs.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSInfrastructureRoleforExpressGatewayServices"
                )
            ],
        )

        # ── CloudWatch log group ───────────────────────────────────
        log_group = logs.LogGroup(
            self,
            "UILogGroup",
            log_group_name=f"/ecs/media-contracts-ui-{deployment_id}-{stack_suffix}",
        )

        # ── Express Gateway Service ────────────────────────────────
        ecr_image_uri = (
            f"{self.account}.dkr.ecr.{self.region}.amazonaws.com"
            f"/media-contracts-ui-{deployment_id}-{stack_suffix}:{image_tag}"
        )

        # SSM parameter ARN helper
        def _ssm_arn(param_name: str) -> str:
            return f"arn:aws:ssm:{self.region}:{self.account}:parameter{param_name}"

        self.express_service = ecs.CfnExpressGatewayService(
            self,
            "ExpressService",
            execution_role_arn=self.exec_role.role_arn,
            infrastructure_role_arn=self.infra_role.role_arn,
            task_role_arn=self.task_role.role_arn,
            service_name=f"media-contracts-{deployment_id}-{stack_suffix}",
            cluster="default",
            cpu="1024",
            memory="2048",
            health_check_path="/api/env",
            network_configuration=ecs.CfnExpressGatewayService.ExpressGatewayServiceNetworkConfigurationProperty(
                subnets=private_subnet_ids,
                security_groups=[ui_task_sg_id],
            ),
            primary_container=ecs.CfnExpressGatewayService.ExpressGatewayContainerProperty(
                image=ecr_image_uri,
                container_port=8080,
                environment=[
                    ecs.CfnExpressGatewayService.KeyValuePairProperty(
                        name="AWS_REGION",
                        value=self.region,
                    ),
                ],
                secrets=[
                    ecs.CfnExpressGatewayService.SecretProperty(
                        name="NODE_ENV",
                        value_from=node_env_param.parameter_arn,
                    ),
                    ecs.CfnExpressGatewayService.SecretProperty(
                        name="ORCHESTRATOR_RUNTIME_ARN",
                        value_from=_ssm_arn(f"{ssm_prefix}/orchestrator-runtime-arn"),
                    ),
                    ecs.CfnExpressGatewayService.SecretProperty(
                        name="JOBS_TABLE_NAME",
                        value_from=_ssm_arn(f"{ssm_prefix}/jobs-table-name"),
                    ),
                    ecs.CfnExpressGatewayService.SecretProperty(
                        name="CONFIG_BUCKET",
                        value_from=_ssm_arn(f"{ssm_prefix}/config-bucket-name"),
                    ),
                    ecs.CfnExpressGatewayService.SecretProperty(
                        name="RESULTS_BUCKET",
                        value_from=_ssm_arn(f"{ssm_prefix}/results-bucket-name"),
                    ),
                    ecs.CfnExpressGatewayService.SecretProperty(
                        name="SOURCE_BUCKET",
                        value_from=_ssm_arn(f"{ssm_prefix}/source-bucket-name"),
                    ),
                    ecs.CfnExpressGatewayService.SecretProperty(
                        name="CHAT_MODEL",
                        value_from=chat_model_param.parameter_arn,
                    ),
                    ecs.CfnExpressGatewayService.SecretProperty(
                        name="AGENT_MODE",
                        value_from=agent_mode_param.parameter_arn,
                    ),
                    ecs.CfnExpressGatewayService.SecretProperty(
                        name="COGNITO_USER_POOL_ID",
                        value_from=_ssm_arn(f"{ssm_prefix}/cognito-user-pool-id"),
                    ),
                    ecs.CfnExpressGatewayService.SecretProperty(
                        name="COGNITO_DOMAIN",
                        value_from=_ssm_arn(f"{ssm_prefix}/cognito-domain"),
                    ),
                    ecs.CfnExpressGatewayService.SecretProperty(
                        name="CONTRACT_KB_ID",
                        value_from=_ssm_arn(f"{ssm_prefix}/contract-kb-id"),
                    ),
                    ecs.CfnExpressGatewayService.SecretProperty(
                        name="TERMS_KB_ID",
                        value_from=_ssm_arn(f"{ssm_prefix}/terms-kb-id"),
                    ),
                ],
                aws_logs_configuration=ecs.CfnExpressGatewayService.ExpressGatewayServiceAwsLogsConfigurationProperty(
                    log_group=log_group.log_group_name,
                    log_stream_prefix="ui",
                ),
            ),
            tags=[CfnTag(key=k, value=v) for k, v in deployment_tags.items()],
        )
        # ── Cognito callback URL update (AwsCustomResource) ────────
        # After the Express service is created/updated, update the Cognito
        # UI client callback and logout URLs to point at the service endpoint.
        service_endpoint = self.express_service.attr_endpoint

        cognito_update_params = {
            "UserPoolId": cognito_user_pool_id,
            "ClientId": cognito_ui_client_id,
            "CallbackURLs": [f"https://{service_endpoint}/callback"],
            "LogoutURLs": [f"https://{service_endpoint}/"],
            # Preserve existing client settings by re-specifying them
            "AllowedOAuthFlows": ["code"],
            "AllowedOAuthScopes": ["openid", "email", "profile"],
            "AllowedOAuthFlowsUserPoolClient": True,
            "SupportedIdentityProviders": ["COGNITO"],
            "PreventUserExistenceErrors": "ENABLED",
            "EnableTokenRevocation": True,
            "AccessTokenValidity": 8,
            "IdTokenValidity": 8,
            "RefreshTokenValidity": 30,
            "TokenValidityUnits": {
                "AccessToken": "hours",
                "IdToken": "hours",
                "RefreshToken": "days",
            },
            "ExplicitAuthFlows": ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"],
        }

        cognito_callback_update = cr.AwsCustomResource(
            self,
            "CognitoCallbackUpdate",
            on_create=cr.AwsSdkCall(
                service="CognitoIdentityServiceProvider",
                action="updateUserPoolClient",
                parameters=cognito_update_params,
                physical_resource_id=cr.PhysicalResourceId.of(
                    f"cognito-callback-{deployment_id}"
                ),
            ),
            on_update=cr.AwsSdkCall(
                service="CognitoIdentityServiceProvider",
                action="updateUserPoolClient",
                parameters=cognito_update_params,
                physical_resource_id=cr.PhysicalResourceId.of(
                    f"cognito-callback-{deployment_id}"
                ),
            ),
            # No on_delete — Cognito client cleanup is handled by CognitoStack
            policy=cr.AwsCustomResourcePolicy.from_statements(
                [
                    iam.PolicyStatement(
                        actions=[
                            "cognito-idp:UpdateUserPoolClient",
                            "cognito-idp:DescribeUserPoolClient",
                        ],
                        resources=[
                            f"arn:aws:cognito-idp:{self.region}:{self.account}:userpool/{cognito_user_pool_id}",
                        ],
                    )
                ]
            ),
        )
        cognito_callback_update.node.add_dependency(self.express_service)

        # ── Outputs ────────────────────────────────────────────────
        CfnOutput(
            self,
            "ServiceArn",
            value=self.express_service.attr_service_arn,
            export_name=f"{self.stack_name}-ServiceArn",
        )
        CfnOutput(
            self,
            "ServiceEndpoint",
            value=self.express_service.attr_endpoint,
            export_name=f"{self.stack_name}-ServiceEndpoint",
        )
        CfnOutput(
            self,
            "TaskRoleArn",
            value=self.task_role.role_arn,
            export_name=f"{self.stack_name}-TaskRoleArn",
        )
        CfnOutput(
            self,
            "ExecRoleArn",
            value=self.exec_role.role_arn,
            export_name=f"{self.stack_name}-ExecRoleArn",
        )

        # ── CDK Nag suppressions ───────────────────────────────────
        NagSuppressions.add_resource_suppressions(
            self.task_role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "bedrock-agent-runtime:RetrieveAndGenerate and Retrieve have no resource-level support — wildcard required by the service.",
                    "appliesTo": ["Resource::*"],
                },
            ],
            apply_to_children=True,
        )

        # Task 5.1: IAM5 suppressions for TaskRole prefix-scoped wildcards
        NagSuppressions.add_resource_suppressions(
            self.task_role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "S3 object paths use prefix-scoped wildcards — individual object keys "
                    "are dynamic job IDs that cannot be enumerated at deploy time.",
                    "appliesTo": [
                        f"Resource::<ConfigBucket2112C5EC.Arn>/*",
                        f"Resource::<SourceBucketDDD2130A.Arn>/*",
                        f"Resource::<ResultsBucketA95A2103.Arn>/jobs-canonical-versions/*",
                        f"Resource::<SourceBucketDDD2130A.Arn>/testing/*",
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "Bedrock cross-region inference requires region wildcard in model ARNs — "
                    "scoped to specific named foundation models and inference profiles.",
                    "appliesTo": [
                        "Resource::arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6",
                        "Resource::arn:aws:bedrock:*::foundation-model/anthropic.claude-opus-4-6-v1",
                        "Resource::arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0",
                        "Resource::arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
                        "Resource::arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v2:0",
                        f"Resource::arn:aws:bedrock:*:<AWS::AccountId>:inference-profile/us.anthropic.claude-sonnet-4-6",
                        f"Resource::arn:aws:bedrock:*:<AWS::AccountId>:inference-profile/us.anthropic.claude-opus-4-6-v1",
                        f"Resource::arn:aws:bedrock:*:<AWS::AccountId>:inference-profile/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
                        f"Resource::arn:aws:bedrock:*:<AWS::AccountId>:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0",
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "bedrock-agentcore:InvokeAgentRuntime requires runtime/* because the runtime ID "
                    "is generated at deploy time and not available as a CDK cross-stack reference.",
                    "appliesTo": [
                        f"Resource::arn:aws:bedrock-agentcore:{self.region}:<AWS::AccountId>:runtime/*",
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "CDK DynamoDB policy adds /index/* suffix for GSI access — "
                    "table ARN is already scoped to the specific jobs table.",
                    "appliesTo": [
                        f"Resource::<ContractReviewJobs82734A0C.Arn>/index/*"
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

        # Task 5.2: IAM5 suppression for TaskExecRole SSM parameter wildcard
        NagSuppressions.add_resource_suppressions(
            self.exec_role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "SSM parameters are prefix-scoped to /mc-{stack_suffix}/ — ECS reads "
                    "all parameters under this prefix at container startup for secret injection.",
                    "appliesTo": [
                        f"Resource::arn:aws:ssm:{self.region}:<AWS::AccountId>:parameter/mc-{stack_suffix}/*",
                    ],
                },
            ],
            apply_to_children=True,
        )

        NagSuppressions.add_resource_suppressions(
            self.exec_role,
            [
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": "AmazonECSTaskExecutionRolePolicy is the AWS-managed policy required for ECS task execution — pulling images and writing logs.",
                    "appliesTo": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
                    ],
                },
            ],
            apply_to_children=True,
        )
        NagSuppressions.add_resource_suppressions(
            self.infra_role,
            [
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": "AmazonECSInfrastructureRoleforExpressGatewayServices is the AWS-managed policy required for ECS Express service infrastructure management.",
                    "appliesTo": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices"
                    ],
                },
            ],
            apply_to_children=True,
        )
        # Task 5.3: AwsCustomResource (CognitoCallbackUpdate) framework findings
        NagSuppressions.add_resource_suppressions(
            cognito_callback_update,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "AwsCustomResource framework Lambda requires wildcard for log group creation.",
                    "appliesTo": ["Resource::*"],
                },
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": "AwsCustomResource framework uses AWSLambdaBasicExecutionRole managed policy.",
                    "appliesTo": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
                    ],
                },
                {
                    "id": "AwsSolutions-L1",
                    "reason": "AwsCustomResource framework manages its own Lambda runtime version.",
                },
            ],
            apply_to_children=True,
        )

        # Task 5.3b: Stack-level suppressions for AwsCustomResource child resources
        # (IAM4 and L1 findings on AWS679f53fac002430cb0da5b7982bd2287 singleton Lambda)
        NagSuppressions.add_stack_suppressions(
            self,
            [
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": "AwsCustomResource (CognitoCallbackUpdate) framework uses AWSLambdaBasicExecutionRole — cannot be overridden.",
                    "appliesTo": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
                    ],
                },
                {
                    "id": "AwsSolutions-L1",
                    "reason": "AwsCustomResource (CognitoCallbackUpdate) framework manages its own Lambda runtime version.",
                },
            ],
        )

    def _apply_common_tags(self) -> None:
        for k, v in self.deployment_tags.items():
            Tags.of(self).add(k, v)
