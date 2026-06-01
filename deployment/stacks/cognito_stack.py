"""Cognito Stack for MediaContracts.

Two app clients on one user pool:

1. UI Client (OIDC authorization code + PKCE)
   - Used by the React frontend via react-oidc-context
   - No client secret (public client, PKCE only)
   - Scopes: openid email profile
   - Callback URLs configured at deploy time via UI_CALLBACK_URL env var

2. Gateway Client (OAuth 2.0 client credentials, M2M)
   - Used by the orchestrator runtime to get tokens for Gateway auth
   - Has a client secret (stored in Secrets Manager)
   - Scope: agentcore-gateway/invoke
   - Credentials stored in Secrets Manager at /media-contracts/cognito-gateway-secret

Groups:
  - admin  : full access to all UI tabs
  - analyst: read-only access to results and KB chat

SSM parameters written (for CDK cross-stack references):
  /media-contracts/cognito-user-pool-id
  /media-contracts/cognito-ui-client-id
  /media-contracts/cognito-authority
  /media-contracts/cognito-domain
  /media-contracts/cognito-gateway-secret-arn
"""

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    Tags,
    CfnOutput,
    aws_cognito as cognito,
    aws_secretsmanager as secretsmanager,
    aws_ssm as ssm,
)
from constructs import Construct
from cdk_nag import NagSuppressions


class CognitoStack(Stack):
    """Cognito User Pool with UI and Gateway app clients."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        deployment_id: str,
        stack_suffix: str,
        deployment_tags: dict[str, str],
        ui_callback_url: str = "http://localhost:7870/callback",
        ui_logout_url: str = "http://localhost:7870/",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.deployment_id = deployment_id
        self.deployment_tags = deployment_tags
        self._apply_common_tags()

        # ── User Pool ──────────────────────────────────────────────
        self.user_pool = cognito.UserPool(
            self,
            "UserPool",
            user_pool_name=f"media-contracts-users-{deployment_id}-{stack_suffix}",
            self_sign_up_enabled=False,  # admin-only provisioning — no public signup
            sign_in_aliases=cognito.SignInAliases(username=True, email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True),
            ),
            password_policy=cognito.PasswordPolicy(
                min_length=12,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True,
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            mfa=cognito.Mfa.REQUIRED,
            mfa_second_factor=cognito.MfaSecondFactor(sms=False, otp=True),
            standard_threat_protection_mode=cognito.StandardThreatProtectionMode.FULL_FUNCTION,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ── Groups ─────────────────────────────────────────────────
        cognito.CfnUserPoolGroup(
            self,
            "AdminGroup",
            user_pool_id=self.user_pool.user_pool_id,
            group_name="admin",
            description="Full access - all UI tabs",
        )
        cognito.CfnUserPoolGroup(
            self,
            "AnalystGroup",
            user_pool_id=self.user_pool.user_pool_id,
            group_name="analyst",
            description="Read-only - results browser and KB chat",
        )

        # ── Cognito domain (managed login v2) ──────────────────────
        self.domain_prefix = f"media-contracts-{deployment_id}-{stack_suffix}"
        self.cfn_domain = cognito.CfnUserPoolDomain(
            self,
            "Domain",
            domain=self.domain_prefix,
            user_pool_id=self.user_pool.user_pool_id,
            managed_login_version=2,
        )

        # ── Resource server for Gateway M2M scope ──────────────────
        self.resource_server = self.user_pool.add_resource_server(
            "GatewayResourceServer",
            identifier="agentcore-gateway",
            scopes=[
                cognito.ResourceServerScope(
                    scope_name="invoke",
                    scope_description="Invoke AgentCore Gateway specialist tools",
                )
            ],
        )

        # ── App Client 1: UI (OIDC, public, PKCE) ─────────────────
        self.ui_client = self.user_pool.add_client(
            "UIClient",
            user_pool_client_name=f"media-contracts-ui-{deployment_id}-{stack_suffix}",
            generate_secret=False,  # public client — no secret
            auth_flows=cognito.AuthFlow(
                user_srp=True,
            ),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(
                    authorization_code_grant=True,
                ),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE,
                ],
                callback_urls=[ui_callback_url],
                logout_urls=[ui_logout_url],
            ),
            prevent_user_existence_errors=True,
            access_token_validity=Duration.hours(8),
            id_token_validity=Duration.hours(8),
            refresh_token_validity=Duration.days(30),
            enable_token_revocation=True,
        )

        # ── App Client 2: Gateway M2M (client credentials) ─────────
        self.gateway_client = self.user_pool.add_client(
            "GatewayClient",
            user_pool_client_name=f"media-contracts-gateway-{deployment_id}-{stack_suffix}",
            generate_secret=True,  # M2M requires a secret
            auth_flows=cognito.AuthFlow(),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(
                    client_credentials=True,
                ),
                scopes=[
                    cognito.OAuthScope.custom("agentcore-gateway/invoke"),
                ],
            ),
            prevent_user_existence_errors=True,
            access_token_validity=Duration.hours(1),
        )
        self.gateway_client.node.add_dependency(self.resource_server)

        # ── Secrets Manager — Gateway client secret only ───────────
        # Only the actual secret value goes here. client_id and token_endpoint
        # are non-sensitive config stored in SSM instead.
        self.gateway_secret = secretsmanager.Secret(
            self,
            "GatewaySecret",
            secret_name=f"mc-{stack_suffix}/cognito-gateway-{deployment_id}",
            description="Cognito M2M client secret for orchestrator → Gateway auth",
            secret_string_value=self.gateway_client.user_pool_client_secret,
        )

        # ── SSM parameters ─────────────────────────────────────────
        authority = (
            f"https://cognito-idp.{self.region}.amazonaws.com"
            f"/{self.user_pool.user_pool_id}"
        )
        domain_url = f"https://media-contracts-{deployment_id}-{stack_suffix}.auth.{self.region}.amazoncognito.com"

        ssm.StringParameter(
            self,
            "UserPoolIdParam",
            parameter_name=f"/mc-{stack_suffix}/cognito-user-pool-id",
            string_value=self.user_pool.user_pool_id,
            description="Cognito User Pool ID",
        )
        ssm.StringParameter(
            self,
            "UIClientIdParam",
            parameter_name=f"/mc-{stack_suffix}/cognito-ui-client-id",
            string_value=self.ui_client.user_pool_client_id,
            description="Cognito UI app client ID (public, PKCE)",
        )
        ssm.StringParameter(
            self,
            "AuthorityParam",
            parameter_name=f"/mc-{stack_suffix}/cognito-authority",
            string_value=authority,
            description="OIDC authority URL for react-oidc-context",
        )
        ssm.StringParameter(
            self,
            "DomainParam",
            parameter_name=f"/mc-{stack_suffix}/cognito-domain",
            string_value=domain_url,
            description="Cognito hosted UI domain URL",
        )
        ssm.StringParameter(
            self,
            "GatewaySecretArnParam",
            parameter_name=f"/mc-{stack_suffix}/cognito-gateway-secret-arn",
            string_value=self.gateway_secret.secret_arn,
            description="Secrets Manager ARN for orchestrator Gateway client secret",
        )
        ssm.StringParameter(
            self,
            "GatewayClientIdParam",
            parameter_name=f"/mc-{stack_suffix}/cognito-gateway-client-id",
            string_value=self.gateway_client.user_pool_client_id,
            description="Cognito M2M app client ID (non-sensitive)",
        )
        ssm.StringParameter(
            self,
            "GatewayTokenEndpointParam",
            parameter_name=f"/mc-{stack_suffix}/cognito-gateway-token-endpoint",
            string_value=f"https://media-contracts-{deployment_id}-{stack_suffix}.auth.{self.region}.amazoncognito.com/oauth2/token",
            description="Cognito token endpoint for client credentials flow (non-sensitive)",
        )

        # ── Outputs ────────────────────────────────────────────────
        CfnOutput(
            self,
            "UserPoolId",
            value=self.user_pool.user_pool_id,
            export_name=f"{self.stack_name}-UserPoolId",
        )
        CfnOutput(
            self,
            "UIClientId",
            value=self.ui_client.user_pool_client_id,
            export_name=f"{self.stack_name}-UIClientId",
        )
        CfnOutput(
            self,
            "GatewayClientId",
            value=self.gateway_client.user_pool_client_id,
            export_name=f"{self.stack_name}-GatewayClientId",
        )
        CfnOutput(
            self,
            "Authority",
            value=authority,
            description="OIDC authority for VITE_COGNITO_AUTHORITY",
        )
        CfnOutput(
            self,
            "CognitoDomain",
            value=domain_url,
            description="Cognito domain for VITE_COGNITO_DOMAIN and logout URL",
        )
        CfnOutput(
            self,
            "GatewaySecretArn",
            value=self.gateway_secret.secret_arn,
            export_name=f"{self.stack_name}-GatewaySecretArn",
        )

        # ── CDK Nag suppressions ───────────────────────────────────
        NagSuppressions.add_resource_suppressions(
            self.user_pool,
            [
                {
                    "id": "AwsSolutions-COG2",
                    "reason": (
                        "self_sign_up_enabled=False is intentional — this pool is "
                        "admin-provisioned only. MFA is REQUIRED via OTP."
                    ),
                }
            ],
        )

        NagSuppressions.add_resource_suppressions(
            self.gateway_secret,
            [
                {
                    "id": "AwsSolutions-SMG4",
                    "reason": (
                        "This secret stores a Cognito M2M client secret. Rotation is performed "
                        "by regenerating the Cognito app client secret and updating this secret — "
                        "Secrets Manager automatic rotation is not applicable for Cognito-managed credentials."
                    ),
                },
            ],
        )

        NagSuppressions.add_stack_suppressions(
            self,
            [
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": (
                        "AwsCustomResource framework uses AWSLambdaBasicExecutionRole — "
                        "cannot be overridden."
                    ),
                    "appliesTo": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
                    ],
                },
                {
                    "id": "AwsSolutions-L1",
                    "reason": "AwsCustomResource framework manages its own Lambda runtime version.",
                },
            ],
        )

    def _apply_common_tags(self) -> None:
        for k, v in self.deployment_tags.items():
            Tags.of(self).add(k, v)
