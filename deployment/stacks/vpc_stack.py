"""VPC Stack for MediaContracts.

Private subnets for all AgentCore runtimes.
NAT gateway for outbound internet (Bedrock API calls).
VPC endpoints for Bedrock, S3, DynamoDB, SSM — keeps traffic off the internet
and avoids NAT costs for AWS service calls.
Flow logs enabled for security audit trail.
"""

from aws_cdk import (
    Stack,
    Tags,
    CfnOutput,
    aws_ec2 as ec2,
)
from constructs import Construct
from cdk_nag import NagSuppressions


class VpcStack(Stack):
    """VPC with private subnets and AWS service VPC endpoints."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        deployment_id: str,
        stack_suffix: str,
        deployment_tags: dict[str, str],
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.deployment_id = deployment_id
        self.deployment_tags = deployment_tags
        self._apply_common_tags()

        # ── VPC ────────────────────────────────────────────────────
        self.vpc = ec2.Vpc(
            self,
            "MediaContractsVpc",
            vpc_name=f"media-contracts-vpc-{deployment_id}-{stack_suffix}",
            max_azs=2,
            nat_gateways=1,  # single NAT — cost optimised; increase for HA
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )

        # Flow logs — security audit trail
        self.vpc.add_flow_log(
            "FlowLog",
            traffic_type=ec2.FlowLogTrafficType.ALL,
        )

        # ── Security groups ────────────────────────────────────────
        # Two SGs with cross-references emitted as separate CfnSecurityGroupIngress/
        # Egress resources (not inline rules). Inline self- and cross-references
        # between SGs create CloudFormation ordering cycles.
        self.runtime_sg = ec2.SecurityGroup(
            self,
            "RuntimeSG",
            vpc=self.vpc,
            security_group_name=f"media-contracts-runtime-sg-{deployment_id}-{stack_suffix}",
            description="Security group for MediaContracts AgentCore runtimes",
            allow_all_outbound=False,
        )

        endpoint_sg = ec2.SecurityGroup(
            self,
            "EndpointSG",
            vpc=self.vpc,
            security_group_name=f"media-contracts-endpoint-sg-{deployment_id}-{stack_suffix}",
            description="Security group for MediaContracts VPC interface endpoints",
            allow_all_outbound=False,
        )

        # Standalone SG rules to avoid inline cross-references (CloudFormation cycle).
        ec2.CfnSecurityGroupEgress(
            self,
            "RuntimeEgressToEndpoint",
            group_id=self.runtime_sg.security_group_id,
            ip_protocol="tcp",
            from_port=443,
            to_port=443,
            destination_security_group_id=endpoint_sg.security_group_id,
            description="HTTPS to VPC interface endpoints",
        )
        ec2.CfnSecurityGroupEgress(
            self,
            "RuntimeEgressToInternet",
            group_id=self.runtime_sg.security_group_id,
            ip_protocol="tcp",
            from_port=443,
            to_port=443,
            cidr_ip="0.0.0.0/0",
            description="HTTPS egress via NAT for AWS services without a VPC endpoint",
        )
        ec2.CfnSecurityGroupIngress(
            self,
            "EndpointIngressFromRuntime",
            group_id=endpoint_sg.security_group_id,
            ip_protocol="tcp",
            from_port=443,
            to_port=443,
            source_security_group_id=self.runtime_sg.security_group_id,
            description="HTTPS from runtime containers",
        )

        # ── VPC Endpoints — keep AWS API traffic off NAT ───────────

        # S3 gateway endpoint (free, no hourly charge)
        s3_endpoint = self.vpc.add_gateway_endpoint(
            "S3Endpoint",
            service=ec2.GatewayVpcEndpointAwsService.S3,
        )
        Tags.of(s3_endpoint).add(
            "Name", f"media-contracts-s3-endpoint-{deployment_id}-{stack_suffix}"
        )

        # DynamoDB gateway endpoint (free)
        ddb_endpoint = self.vpc.add_gateway_endpoint(
            "DynamoDBEndpoint",
            service=ec2.GatewayVpcEndpointAwsService.DYNAMODB,
        )
        Tags.of(ddb_endpoint).add(
            "Name", f"media-contracts-dynamodb-endpoint-{deployment_id}-{stack_suffix}"
        )

        # Bedrock interface endpoint — model invocations stay in VPC
        self.bedrock_endpoint = self.vpc.add_interface_endpoint(
            "BedrockEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.BEDROCK_RUNTIME,
            private_dns_enabled=True,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[endpoint_sg],
            open=False,
        )
        Tags.of(self.bedrock_endpoint).add(
            "Name", f"media-contracts-bedrock-endpoint-{deployment_id}-{stack_suffix}"
        )

        # SSM endpoint — for parameter store reads
        ssm_endpoint = self.vpc.add_interface_endpoint(
            "SSMEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.SSM,
            private_dns_enabled=True,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[endpoint_sg],
            open=False,
        )
        Tags.of(ssm_endpoint).add(
            "Name", f"media-contracts-ssm-endpoint-{deployment_id}-{stack_suffix}"
        )

        # Secrets Manager endpoint
        sm_endpoint = self.vpc.add_interface_endpoint(
            "SecretsManagerEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
            private_dns_enabled=True,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[endpoint_sg],
            open=False,
        )
        Tags.of(sm_endpoint).add(
            "Name",
            f"media-contracts-secretsmanager-endpoint-{deployment_id}-{stack_suffix}",
        )

        # ── UI task security group (ECS Express service) ───────────
        self.ui_task_sg = ec2.SecurityGroup(
            self,
            "UITaskSG",
            vpc=self.vpc,
            security_group_name=f"media-contracts-ui-task-sg-{deployment_id}-{stack_suffix}",
            description="Security group for MediaContracts ECS UI tasks",
            allow_all_outbound=False,
        )
        # Ingress: Express ALB → task on port 8080. The ALB SG is AWS-managed
        # and not exposed via CFN, so we scope to VPC CIDR as a practical equivalent.
        self.ui_task_sg.add_ingress_rule(
            peer=ec2.Peer.ipv4(self.vpc.vpc_cidr_block),
            connection=ec2.Port.tcp(8080),
            description="HTTP from Express ALB (VPC CIDR scope)",
        )
        # Egress: task → AWS APIs via NAT
        self.ui_task_sg.add_egress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(443),
            description="HTTPS egress to AWS APIs via NAT",
        )

        # ── Outputs ────────────────────────────────────────────────
        CfnOutput(
            self, "VpcId", value=self.vpc.vpc_id, export_name=f"{self.stack_name}-VpcId"
        )

        private_subnet_ids = [s.subnet_id for s in self.vpc.private_subnets]
        CfnOutput(
            self,
            "PrivateSubnetIds",
            value=",".join(private_subnet_ids),
            export_name=f"{self.stack_name}-PrivateSubnetIds",
        )

        CfnOutput(
            self,
            "RuntimeSGId",
            value=self.runtime_sg.security_group_id,
            export_name=f"{self.stack_name}-RuntimeSGId",
        )

        CfnOutput(
            self,
            "UITaskSGId",
            value=self.ui_task_sg.security_group_id,
            export_name=f"{self.stack_name}-UITaskSGId",
        )

        # ── CDK Nag suppressions ───────────────────────────────────
        NagSuppressions.add_resource_suppressions(
            self.ui_task_sg,
            [
                {
                    "id": "AwsSolutions-EC23",
                    "reason": "UITaskSG ingress is scoped to VPC CIDR (10.0.0.0/16) for ALB→task traffic on port 8080. "
                    "cdk-nag reports UNKNOWN because the CIDR is a CloudFormation intrinsic that cannot be statically validated.",
                },
                {
                    "id": "CdkNagValidationFailure",
                    "reason": "VPC CIDR is a Fn::GetAtt intrinsic that cdk-nag cannot resolve at synth time — "
                    "the actual CIDR is 10.0.0.0/16, scoped to internal VPC traffic only.",
                },
            ],
        )

        NagSuppressions.add_stack_suppressions(
            self,
            [
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": (
                        "CustomVpcRestrictDefaultSG is a CDK framework construct — "
                        "its managed policy cannot be overridden."
                    ),
                    "appliesTo": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
                    ],
                },
                {
                    "id": "AwsSolutions-L1",
                    "reason": (
                        "CustomVpcRestrictDefaultSG is a CDK framework construct — "
                        "its Lambda runtime is managed by CDK and cannot be overridden."
                    ),
                },
            ],
        )

    def _apply_common_tags(self) -> None:
        for k, v in self.deployment_tags.items():
            Tags.of(self).add(k, v)
