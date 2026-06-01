"""X-Ray Transaction Search Stack for MediaContracts.

Enables CloudWatch Transaction Search at the account level (per-region).
This is a prerequisite for X-Ray tracing with AgentCore Runtime and Gateway.

IMPORTANT: This is a singleton resource per account/region.
Deploying when already enabled will fail with AlreadyExists.
If that happens, either:
  - Remove this stack from the deploy sequence (X-Ray is already on)
  - Or destroy and redeploy

X-Ray annotations added by the runtimes:
  - job_id       : correlates all spans across orchestrator + specialists
  - specialist   : identifies which specialist produced a span
  - contract     : contract filename stem
  - status       : COMPLETE | FAILED | RUNNING

These annotations make it possible to query in X-Ray:
  annotation.job_id = "some-uuid"
  → shows the full trace across all 6 microVMs for one contract review
"""

from aws_cdk import (
    Stack,
    Tags,
    aws_logs as logs,
    aws_xray as xray,
)
from constructs import Construct


class XRayStack(Stack):
    """Account-level X-Ray Transaction Search enablement."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        deployment_id: str,
        stack_suffix: str,
        deployment_tags: dict[str, str],
        indexing_percentage: int = 5,  # 5% of traces indexed (higher than default 1%)
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.deployment_id = deployment_id
        self.deployment_tags = deployment_tags

        for key, value in deployment_tags.items():
            Tags.of(self).add(key, value)

        account = Stack.of(self).account
        region = Stack.of(self).region
        partition = Stack.of(self).partition

        # Resource policy: allow X-Ray to write spans to CloudWatch Logs
        resource_policy = logs.CfnResourcePolicy(
            self,
            "XRayLogResourcePolicy",
            policy_name="MediaContractsTransactionSearchAccess",
            policy_document=(
                '{"Version":"2012-10-17","Statement":[{"Sid":"TransactionSearchXRayAccess",'
                '"Effect":"Allow","Principal":{"Service":"xray.amazonaws.com"},'
                '"Action":"logs:PutLogEvents","Resource":['
                f'"arn:{partition}:logs:{region}:{account}:log-group:aws/spans:*",'
                f'"arn:{partition}:logs:{region}:{account}:log-group:/aws/application-signals/data:*"'
                '],"Condition":{"ArnLike":{'
                f'"aws:SourceArn":"arn:{partition}:xray:{region}:{account}:*"'
                '},"StringEquals":{"aws:SourceAccount":"' + account + '"}}}]}'
            ),
        )

        # Enable Transaction Search (account-level singleton)
        transaction_search = xray.CfnTransactionSearchConfig(
            self,
            "XRayTransactionSearchConfig",
            indexing_percentage=indexing_percentage,
        )
        transaction_search.node.add_dependency(resource_policy)
