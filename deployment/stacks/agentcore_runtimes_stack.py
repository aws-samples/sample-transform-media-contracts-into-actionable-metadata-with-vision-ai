"""AgentCore Runtimes Stack for MediaContracts.

Creates ONE AgentCore Runtime — the orchestrator.

Specialists are Lambda functions behind the AgentCore Gateway (not runtimes).
The orchestrator connects to the Gateway via MCP to discover and invoke them.
"""

from __future__ import annotations

from aws_cdk import (
    Stack,
    Tags,
    CfnOutput,
    aws_bedrockagentcore as agentcore,
    aws_iam as iam,
    aws_kms as kms,
    aws_logs as logs,
    aws_ssm as ssm,
)
from aws_cdk.mixins_preview.aws_bedrockagentcore import mixins as agentcore_mixins
from constructs import Construct


class AgentCoreRuntimesStack(Stack):
    """Orchestrator AgentCore Runtime."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        deployment_id: str,
        stack_suffix: str,
        deployment_tags: dict[str, str],
        orchestrator_ecr_uri: str,
        orchestrator_role: iam.Role,
        kms_key: kms.Key,
        config_bucket_name: str,
        results_bucket_name: str,
        source_bucket_name: str,
        jobs_table_name: str,
        gateway_url: str,
        cognito_secret_arn: str,
        cognito_gateway_client_id: str,
        cognito_token_endpoint: str,
        private_subnet_ids: list[str],
        runtime_sg_id: str,
        model_id: str = "us.anthropic.claude-sonnet-4-6",
        image_tag: str = "latest",
        # Inference profile ARNs for cost tracking
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

        log_prefix = f"/aws/bedrock-agentcore/runtimes/media-contracts-orchestrator-{deployment_id}-{stack_suffix}"

        self.app_log_group = logs.LogGroup(
            self,
            "OrchestratorAppLogs",
            log_group_name=f"{log_prefix}/app",
            retention=logs.RetentionDays.ONE_YEAR,
            encryption_key=kms_key,
        )
        usage_log_group = logs.LogGroup(
            self,
            "OrchestratorUsageLogs",
            log_group_name=f"{log_prefix}/usage",
            retention=logs.RetentionDays.ONE_YEAR,
            encryption_key=kms_key,
        )

        self.orchestrator_runtime = agentcore.CfnRuntime(
            self,
            "OrchestratorRuntime",
            agent_runtime_name=f"media_contracts_orchestrator_{deployment_id}_{stack_suffix}",
            description=f"MediaContracts orchestrator for deployment {deployment_id} - extracts contracts, fans out to Gateway specialists",
            agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                container_configuration=agentcore.CfnRuntime.ContainerConfigurationProperty(
                    container_uri=f"{orchestrator_ecr_uri}:{image_tag}",
                )
            ),
            network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(
                network_mode="VPC",
                network_mode_config=agentcore.CfnRuntime.VpcConfigProperty(
                    subnets=private_subnet_ids,
                    security_groups=[runtime_sg_id],
                ),
            ),
            protocol_configuration="HTTP",
            role_arn=orchestrator_role.role_arn,
            tags={
                "deployment_id": deployment_id,
                "project": "media-contracts",
                "managed_by": "cdk",
            },
            environment_variables={
                "AWS_DEFAULT_REGION": self.region,
                "CONFIG_BUCKET": config_bucket_name,
                "RESULTS_BUCKET": results_bucket_name,
                "SOURCE_BUCKET": source_bucket_name,
                "JOBS_TABLE_NAME": jobs_table_name,
                "GATEWAY_URL": gateway_url,
                "COGNITO_SECRET_ARN": cognito_secret_arn,
                "COGNITO_GATEWAY_CLIENT_ID": cognito_gateway_client_id,
                "COGNITO_TOKEN_ENDPOINT": cognito_token_endpoint,
                "MODEL_ID": model_id,
                "LOG_LEVEL": "INFO",
                # Inference profile ARNs — all Bedrock calls use these for cost tracking
                "SONNET_46_PROFILE_ARN": sonnet_46_profile_arn,
                "OPUS_46_PROFILE_ARN": opus_46_profile_arn,
                "SONNET_45_PROFILE_ARN": sonnet_45_profile_arn,
                "HAIKU_45_PROFILE_ARN": haiku_45_profile_arn,
            },
        )

        agentcore_mixins.CfnRuntimeLogsMixin.APPLICATION_LOGS.to_log_group(
            self.app_log_group
        ).apply_to(self.orchestrator_runtime)
        agentcore_mixins.CfnRuntimeLogsMixin.USAGE_LOGS.to_log_group(
            usage_log_group
        ).apply_to(self.orchestrator_runtime)
        agentcore_mixins.CfnRuntimeLogsMixin.TRACES.to_x_ray().apply_to(
            self.orchestrator_runtime
        )

        # CDK's AgentCore log-delivery mixin synthesizes an AWS::Logs::ResourcePolicy
        # that grants delivery.logs.amazonaws.com write access to the two log groups.
        # That policy is redundant — AWS already provisions the account-wide
        # AWSLogDeliveryWrite20150319 resource policy on first use of log delivery,
        # and the account has a hard limit of 10 resource policies per region.
        # We remove the redundant policy here to stay under that limit.
        from aws_cdk import aws_logs as _logs_for_prune

        for child in list(self.node.find_all()):
            if isinstance(child, _logs_for_prune.CfnResourcePolicy):
                child.node.try_remove_child("Resource")
                # Detach from the stack so it isn't synthesized at all
                parent = child.node.scope
                if parent is not None:
                    parent.node.try_remove_child(child.node.id)

        # Write ARN to SSM for ECS task to read
        ssm.StringParameter(
            self,
            "OrchestratorRuntimeArnParam",
            parameter_name=f"/mc-{stack_suffix}/orchestrator-runtime-arn",
            string_value=self.orchestrator_runtime.attr_agent_runtime_arn,
            description="AgentCore orchestrator runtime ARN",
        )

        CfnOutput(
            self,
            "OrchestratorRuntimeArn",
            value=self.orchestrator_runtime.attr_agent_runtime_arn,
            export_name=f"{self.stack_name}-OrchestratorRuntimeArn",
        )
        CfnOutput(
            self,
            "OrchestratorRuntimeId",
            value=self.orchestrator_runtime.attr_agent_runtime_id,
            export_name=f"{self.stack_name}-OrchestratorRuntimeId",
        )

    def _apply_common_tags(self) -> None:
        for k, v in self.deployment_tags.items():
            Tags.of(self).add(k, v)
