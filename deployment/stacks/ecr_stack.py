"""ECR Stack for MediaContracts.

One repository for the orchestrator container.
Specialist Lambdas use Lambda's built-in packaging — no ECR needed.
"""

from aws_cdk import (
    RemovalPolicy,
    Stack,
    Tags,
    CfnOutput,
    aws_ecr as ecr,
)
from constructs import Construct


class ECRStack(Stack):
    """ECR repository for the orchestrator AgentCore Runtime container."""

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

        self.repositories: dict[str, ecr.Repository] = {}

        # Orchestrator container repo
        orchestrator_repo = ecr.Repository(
            self,
            "OrchestratorRepo",
            repository_name=f"media-contracts-orchestrator-{deployment_id}-{stack_suffix}",
            image_tag_mutability=ecr.TagMutability.MUTABLE,
            removal_policy=RemovalPolicy.DESTROY,
            empty_on_delete=True,
            image_scan_on_push=True,
            lifecycle_rules=[
                ecr.LifecycleRule(description="Keep last 5 images", max_image_count=5)
            ],
        )
        self.repositories["orchestrator"] = orchestrator_repo

        # UI container repo
        ui_repo = ecr.Repository(
            self,
            "UIRepo",
            repository_name=f"media-contracts-ui-{deployment_id}-{stack_suffix}",
            image_tag_mutability=ecr.TagMutability.MUTABLE,
            removal_policy=RemovalPolicy.DESTROY,
            empty_on_delete=True,
            image_scan_on_push=True,
            lifecycle_rules=[
                ecr.LifecycleRule(description="Keep last 5 images", max_image_count=5)
            ],
        )
        self.repositories["ui"] = ui_repo

        CfnOutput(
            self,
            "OrchestratorRepoUri",
            value=orchestrator_repo.repository_uri,
            export_name=f"{self.stack_name}-OrchestratorRepoUri",
        )
        CfnOutput(
            self,
            "UIRepoUri",
            value=ui_repo.repository_uri,
            export_name=f"{self.stack_name}-UIRepoUri",
        )

    def _apply_common_tags(self) -> None:
        for k, v in self.deployment_tags.items():
            Tags.of(self).add(k, v)
