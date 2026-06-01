"""AgentCore Gateway Stack for MediaContracts.

Registers each specialist as a Lambda-backed MCP tool target.
The orchestrator connects to this Gateway and uses semantic search
to discover and invoke the right specialists based on contract content.

In agent mode: orchestrator reasons freely over all tools.
In user mode:  orchestrator receives a constrained tool list matching
               the user's selection from LegalTeam.jsx.

Tool naming convention:
  - Target names use hyphens (required by CloudFormation pattern ^([0-9a-zA-Z][-]?){1,100}$)
  - Schema JSON name fields also use hyphens to match target names
  - This produces clean Gateway tool names: "talent-guild-compliance___talent-guild-compliance"
  - Internal identifiers (S3 paths, DynamoDB, Lambda names, UI IDs) continue using underscores

Tool descriptions are rich semantic text so the LLM can reason about which
specialists are relevant for a given contract type.
"""

from aws_cdk import (
    CustomResource,
    Duration,
    Stack,
    CfnOutput,
    Tags,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_s3 as s3,
)
from aws_cdk.custom_resources import Provider
from constructs import Construct
import cdk_nag

try:
    import aws_cdk.aws_bedrock_agentcore_alpha as agentcore
except ImportError:
    import aws_cdk_aws_bedrock_agentcore_alpha as agentcore  # type: ignore


# Rich semantic descriptions — used by the Gateway's semantic search
# so the orchestrator LLM can reason about which tools to invoke
SPECIALIST_DESCRIPTIONS = {
    "financial": (
        "Analyzes deal economics, revenue share, minimum guarantees, MFN provisions, "
        "payment terms, and audit rights. Use for contracts involving "
        "money, compensation, licensing fees, or revenue splits."
    ),
    "rights_clearance": (
        "Analyzes IP ownership, chain of title, licensing scope, exclusivity, "
        "territorial rights, holdbacks, and reversion clauses. Use for IP, "
        "content licensing, or distribution rights contracts."
    ),
    "talent_guild_compliance": (
        "Analyzes SAG-AFTRA, WGA, DGA obligations, residual payments, performer "
        "protections, and union jurisdiction. Use for contracts involving talent, "
        "writers, directors, or guild-covered personnel."
    ),
    "regulatory_compliance": (
        "Analyzes GDPR, content quotas, accessibility mandates, export controls, "
        "and jurisdiction-specific requirements. Use for international distribution "
        "or regulated content contracts."
    ),
    "risk_strategist": (
        "Synthesizes specialist analyses into a unified risk assessment and "
        "negotiation roadmap. Prioritizes issues by severity and recommends "
        "protective clauses. Run after all other specialists."
    ),
    "handwriting_analyzer": (
        "Analyzes handwritten annotations, signatures, and amendments in contracts. "
        "Use when the contract contains handwritten modifications or initials "
        "that may affect the agreement's terms."
    ),
}


class GatewayStack(Stack):
    """AgentCore Gateway with specialist Lambda tool targets."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        deployment_id: str,
        stack_suffix: str,
        deployment_tags: dict[str, str],
        specialist_lambdas: dict[str, lambda_.Function],
        config_bucket: s3.Bucket,
        cognito_user_pool_id: str,
        cognito_client_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.deployment_id = deployment_id
        self.deployment_tags = deployment_tags
        self._apply_common_tags()

        # ── Gateway execution role ─────────────────────────────────
        self.gateway_role = iam.Role(
            self,
            "GatewayRole",
            role_name=f"media-contracts-gateway-role-{deployment_id}-{stack_suffix}",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            description="Execution role for MediaContracts AgentCore Gateway",
        )

        # S3 read — scoped to the specific tool schema objects the Gateway reads.
        schema_object_arns = [
            f"{config_bucket.bucket_arn}/schemas/specialists/{name}.json"
            for name in specialist_lambdas.keys()
        ]
        self.gateway_role.add_to_policy(
            iam.PolicyStatement(
                sid="ToolSchemaRead",
                actions=["s3:GetObject"],
                resources=schema_object_arns,
            )
        )

        # CloudWatch Logs — scoped to the Gateway's own log group name.
        gateway_log_group_name = f"/aws/bedrock-agentcore/gateway/media-contracts-gateway-{deployment_id}-{stack_suffix}"
        self.gateway_role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudWatchLogsCreate",
                actions=["logs:CreateLogGroup"],
                resources=[
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:{gateway_log_group_name}"
                ],
            )
        )
        self.gateway_role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudWatchLogsStreams",
                actions=[
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=[
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:{gateway_log_group_name}:log-stream:*"
                ],
            )
        )

        # ── Gateway ────────────────────────────────────────────────
        discovery_url = (
            f"https://cognito-idp.{self.region}.amazonaws.com"
            f"/{cognito_user_pool_id}/.well-known/openid-configuration"
        )

        self.gateway = agentcore.Gateway(
            self,
            "SpecialistsGateway",
            gateway_name=f"media-contracts-gateway-{deployment_id}-{stack_suffix}",
            description=(
                "MCP Gateway for MediaContracts specialist agents. "
                "Each tool is a domain expert for a specific aspect of media contract review."
            ),
            role=self.gateway_role,
            protocol_configuration=agentcore.McpProtocolConfiguration(
                instructions=(
                    "You are orchestrating a media contract review. "
                    "Select the appropriate specialist tools based on the contract type and content. "
                    "Each tool is an expert in a specific domain of media contract law and business affairs. "
                    "You may call multiple tools in parallel when their domains are independent."
                ),
                search_type=agentcore.McpGatewaySearchType.SEMANTIC,
                supported_versions=[agentcore.MCPProtocolVersion.MCP_2025_03_26],
            ),
            authorizer_configuration=agentcore.GatewayAuthorizer.using_custom_jwt(
                discovery_url=discovery_url,
                allowed_clients=[cognito_client_id],
            ),
        )

        # ── Register specialist Lambda targets ─────────────────────
        # Grant invoke permissions explicitly on specific Lambda ARNs (no version wildcard).
        specialist_arns = [fn.function_arn for fn in specialist_lambdas.values()]
        self.gateway_role.add_to_policy(
            iam.PolicyStatement(
                sid="InvokeSpecialistLambdas",
                actions=["lambda:InvokeFunction"],
                resources=specialist_arns,
            )
        )

        # Collect policy nodes for dependency ordering
        policy_deps = [
            child
            for child in self.gateway_role.node.children
            if child.node.id in ("DefaultPolicy",)
            or child.node.id.startswith("OverflowPolicy")
        ]

        self.targets: dict[str, object] = {}
        # Generate a deploy-time hash of all schema files so CDK detects
        # content changes even when the S3 keys stay the same.
        import hashlib
        from pathlib import Path as _Path

        schema_dir = _Path(__file__).resolve().parents[2] / "schemas" / "specialists"
        schema_hash = hashlib.md5(usedforsecurity=False)
        for sf in sorted(schema_dir.glob("*.json")):
            schema_hash.update(sf.read_bytes())
        _schema_fingerprint = schema_hash.hexdigest()[:8]

        for specialist_name, fn in specialist_lambdas.items():
            target_name = specialist_name.replace("_", "-")
            description = SPECIALIST_DESCRIPTIONS.get(
                specialist_name, f"{specialist_name} specialist"
            )

            target = self.gateway.add_lambda_target(
                f"Target-{specialist_name}",
                gateway_target_name=target_name,
                description=f"{description[:180]} [{_schema_fingerprint}]",
                lambda_function=fn,
                tool_schema=agentcore.ToolSchema.from_s3_file(
                    bucket=config_bucket,
                    object_key=f"schemas/specialists/{specialist_name}.json",
                ),
            )

            for dep in policy_deps:
                target.node.add_dependency(dep)

            self.targets[specialist_name] = target

        # ── Gateway observability (log delivery + tracing) ─────────
        self.gateway_log_group = logs.LogGroup(
            self,
            "GatewayLogGroup",
            log_group_name=f"/aws/vendedlogs/bedrock-agentcore/gateway/{self.gateway.gateway_id}",
            retention=logs.RetentionDays.ONE_YEAR,
        )

        # Lambda-backed custom resource to configure CloudWatch log delivery
        # and X-Ray tracing via the CloudWatch Logs delivery API.
        observability_fn = lambda_.Function(
            self,
            "GatewayObservabilityFn",
            function_name=f"media-contracts-gw-observability-{deployment_id}-{stack_suffix}",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="index.handler",
            timeout=Duration.seconds(60),
            code=lambda_.Code.from_inline(self._observability_lambda_code()),
        )

        observability_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:PutDeliverySource",
                    "logs:DeleteDeliverySource",
                    "logs:PutDeliveryDestination",
                    "logs:DeleteDeliveryDestination",
                    "logs:CreateDelivery",
                    "logs:DeleteDelivery",
                    "logs:GetDelivery",
                    "logs:DescribeDeliveries",
                    "logs:DescribeDeliverySources",
                    "logs:DescribeDeliveryDestinations",
                ],
                resources=["*"],
            )
        )
        observability_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "xray:PutResourcePolicy",
                    "xray:DeleteResourcePolicy",
                    "xray:ListResourcePolicies",
                ],
                resources=["*"],
            )
        )
        observability_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:AllowVendedLogDeliveryForResource",
                ],
                resources=[self.gateway.gateway_arn],
            )
        )

        observability_provider = Provider(
            self,
            "GatewayObservabilityProvider",
            on_event_handler=observability_fn,
        )

        CustomResource(
            self,
            "GatewayObservabilityCR",
            service_token=observability_provider.service_token,
            properties={
                "GatewayArn": self.gateway.gateway_arn,
                "GatewayId": self.gateway.gateway_id,
                "LogGroupArn": self.gateway_log_group.log_group_arn,
                "DeploymentId": deployment_id,
                "Version": "v3",
            },
        )

        # ── Outputs ────────────────────────────────────────────────
        CfnOutput(
            self,
            "GatewayUrl",
            value=self.gateway.gateway_url or "",
            export_name=f"{self.stack_name}-GatewayUrl",
        )
        CfnOutput(
            self,
            "GatewayId",
            value=self.gateway.gateway_id,
            export_name=f"{self.stack_name}-GatewayId",
        )
        CfnOutput(
            self,
            "GatewayArn",
            value=self.gateway.gateway_arn,
            export_name=f"{self.stack_name}-GatewayArn",
        )
        CfnOutput(
            self,
            "GatewayRoleArn",
            value=self.gateway_role.role_arn,
            export_name=f"{self.stack_name}-GatewayRoleArn",
        )

        # ── CDK Nag suppressions ───────────────────────────────────
        # Helper to get the CloudFormation logical ID for cross-stack L2 constructs
        def _logical_id(construct) -> str:
            return Stack.of(construct).get_logical_id(construct.node.default_child)

        # Task 6.1: GatewayRole — AgentCore Gateway construct adds internal
        # permissions with wildcards that cannot be overridden via CDK L2.
        cdk_nag.NagSuppressions.add_resource_suppressions(
            self.gateway_role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "AgentCore Gateway construct adds internal permissions with wildcards "
                    "for gateway management operations — cannot be overridden via CDK L2.",
                    "appliesTo": ["Resource::*"],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "AgentCore Gateway construct adds lambda:InvokeFunction with :* version "
                    "suffix for each target Lambda — required for Gateway to invoke any published version.",
                    "appliesTo": [
                        f"Resource::<{_logical_id(fn)}.Arn>:*"
                        for fn in specialist_lambdas.values()
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "CloudWatch Logs log-stream:* suffix is required — log stream names "
                    "are generated at runtime and cannot be enumerated at deploy time.",
                    "appliesTo": [
                        f"Resource::arn:aws:logs:{self.region}:<AWS::AccountId>:log-group:{gateway_log_group_name}:log-stream:*",
                    ],
                },
            ],
            apply_to_children=True,
        )

        # Task 6.3: GatewayObservabilityFn — CloudWatch Logs delivery APIs
        # and X-Ray resource policy APIs have no resource-level support.
        cdk_nag.NagSuppressions.add_resource_suppressions(
            observability_fn,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "CloudWatch Logs delivery APIs (PutDeliverySource, CreateDelivery, etc.) "
                    "and X-Ray resource policy APIs have no resource-level support — wildcard required.",
                    "appliesTo": ["Resource::*"],
                },
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": "Lambda basic execution role (AWSLambdaBasicExecutionRole) is required "
                    "for CloudWatch Logs access — standard for all Lambda functions.",
                    "appliesTo": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
                    ],
                },
                {
                    "id": "AwsSolutions-L1",
                    "reason": "GatewayObservabilityFn uses Python 3.13 — 3.14 not yet validated for this use case.",
                },
            ],
            apply_to_children=True,
        )

        # Task 6.4: GatewayObservabilityProvider — CDK Provider framework
        # manages its own Lambda runtime and adds wildcard permissions.
        _obs_fn_id = _logical_id(observability_fn)
        cdk_nag.NagSuppressions.add_resource_suppressions(
            observability_provider,
            [
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": "CDK Provider framework uses AWSLambdaBasicExecutionRole — "
                    "cannot be overridden.",
                    "appliesTo": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "CDK Provider framework adds lambda:InvokeFunction with :* version "
                    "suffix for the on-event handler — cannot be overridden.",
                    "appliesTo": [
                        f"Resource::<{_obs_fn_id}.Arn>:*",
                    ],
                },
                {
                    "id": "AwsSolutions-L1",
                    "reason": "CDK Provider framework manages its own Lambda runtime version.",
                },
            ],
            apply_to_children=True,
        )

    @staticmethod
    def _observability_lambda_code() -> str:
        return """
import json
import boto3
import cfnresponse

logs = boto3.client("logs")


def _get_all_deliveries():
    \"\"\"Paginate through all deliveries in the account.\"\"\"
    deliveries = []
    kwargs = {}
    while True:
        resp = logs.describe_deliveries(**kwargs)
        deliveries.extend(resp.get("deliveries", []))
        token = resp.get("nextToken")
        if not token:
            break
        kwargs["nextToken"] = token
    return deliveries


def _get_destination_arn(name):
    \"\"\"Look up a delivery destination ARN by name.\"\"\"
    kwargs = {}
    while True:
        resp = logs.describe_delivery_destinations(**kwargs)
        for d in resp.get("deliveryDestinations", []):
            if d.get("name") == name:
                return d.get("arn")
        token = resp.get("nextToken")
        if not token:
            break
        kwargs["nextToken"] = token
    return None


def _ensure_source(name, log_type, resource_arn):
    try:
        logs.put_delivery_source(
            name=name,
            logType=log_type,
            resourceArn=resource_arn,
        )
        print(f"Created delivery source: {name}")
    except logs.exceptions.ConflictException:
        print(f"Delivery source already exists: {name}")


def _ensure_destination_cwl(name, log_group_arn):
    try:
        logs.put_delivery_destination(
            name=name,
            deliveryDestinationType="CWL",
            deliveryDestinationConfiguration={
                "destinationResourceArn": log_group_arn,
            },
        )
        print(f"Created CWL delivery destination: {name}")
    except logs.exceptions.ConflictException:
        print(f"CWL delivery destination already exists: {name}")


def _ensure_destination_xray(name):
    try:
        logs.put_delivery_destination(
            name=name,
            deliveryDestinationType="XRAY",
        )
        print(f"Created XRAY delivery destination: {name}")
    except logs.exceptions.ConflictException:
        print(f"XRAY delivery destination already exists: {name}")


def _ensure_delivery(source_name, dest_name):
    existing = _get_all_deliveries()
    already = any(d.get("deliverySourceName") == source_name for d in existing)
    if already:
        print(f"Delivery already exists for source: {source_name}")
        return

    dest_arn = _get_destination_arn(dest_name)
    if not dest_arn:
        raise RuntimeError(f"Destination {dest_name} not found after creation")

    logs.create_delivery(
        deliverySourceName=source_name,
        deliveryDestinationArn=dest_arn,
    )
    print(f"Created delivery: {source_name} -> {dest_name}")


def handler(event, context):
    props = event["ResourceProperties"]
    gateway_arn = props["GatewayArn"]
    dep_id = props["DeploymentId"]
    log_group_arn = props["LogGroupArn"]
    request_type = event["RequestType"]

    logs_src = f"mc-gw-logs-{dep_id}"
    traces_src = f"mc-gw-traces-{dep_id}"
    logs_dest = f"mc-gw-logs-dest-{dep_id}"
    traces_dest = f"mc-gw-traces-dest-{dep_id}"

    try:
        if request_type in ("Create", "Update"):
            # Log delivery: source → CWL destination → delivery
            _ensure_source(logs_src, "APPLICATION_LOGS", gateway_arn)
            _ensure_destination_cwl(logs_dest, log_group_arn)
            _ensure_delivery(logs_src, logs_dest)

            # Trace delivery: source → XRAY destination → delivery
            _ensure_source(traces_src, "TRACES", gateway_arn)
            _ensure_destination_xray(traces_dest)
            _ensure_delivery(traces_src, traces_dest)

            cfnresponse.send(event, context, cfnresponse.SUCCESS, {"Status": "OK"})

        elif request_type == "Delete":
            # Clean up: deliveries first, then destinations, then sources
            for delivery in _get_all_deliveries():
                if delivery.get("deliverySourceName") in (logs_src, traces_src):
                    try:
                        logs.delete_delivery(id=delivery["id"])
                        print(f"Deleted delivery: {delivery['id']}")
                    except Exception as e:
                        print(f"Failed to delete delivery {delivery['id']}: {e}")
            for name in (logs_dest, traces_dest):
                try:
                    logs.delete_delivery_destination(name=name)
                    print(f"Deleted destination: {name}")
                except Exception as e:
                    print(f"Failed to delete destination {name}: {e}")
            for name in (logs_src, traces_src):
                try:
                    logs.delete_delivery_source(name=name)
                    print(f"Deleted source: {name}")
                except Exception as e:
                    print(f"Failed to delete source {name}: {e}")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {"Status": "Deleted"})

    except Exception as e:
        print(f"Error: {e}")
        cfnresponse.send(event, context, cfnresponse.FAILED, {"Error": str(e)})
"""

    def _apply_common_tags(self) -> None:
        for k, v in self.deployment_tags.items():
            Tags.of(self).add(k, v)
