"""CloudWatch Dashboard Stack for MediaContracts.

Creates a single operational dashboard with:

  Row 1 — Job Health
    - Jobs COMPLETE vs FAILED (DynamoDB GSI query via metric math)
    - Orchestrator invocation count and error rate

  Row 2 — Specialist Performance
    - Per-specialist Lambda duration (p50 / p95 / p99)
    - Per-specialist Lambda error count

  Row 3 — Pipeline Throughput
    - Orchestrator runtime invocations over time
    - Total Lambda invocations across all specialists

  Row 4 — Infrastructure
    - DynamoDB consumed read/write capacity
    - Lambda throttles across all specialists

  Row 5 — End-to-End Job Metrics
    - Job duration by mode (agent vs user)
    - Jobs completed vs failed by mode

  Row 6 — Cost & Specialist Usage
    - Estimated Bedrock cost per hour
    - Average specialists invoked per job

  Row 7 — Orchestrator Agent Loop (Logs Insights)
    - Model calls per job (bar chart)
    - Tool call latency breakdown (table)

  Row 8 — Pipeline Step Waterfall (Logs Insights)
    - Average time per pipeline step

  Row 9 — Model Call Efficiency (Logs Insights)
    - Stop reason distribution
    - Model call duration trend

  Row 10 — Error Drill-down (Logs Insights)
    - Recent tool call failures with job ID, tool, and error
"""

from aws_cdk import (
    Duration,
    Stack,
    Tags,
    CfnOutput,
    aws_cloudwatch as cw,
    aws_lambda as lambda_,
    aws_logs as logs,
)
from constructs import Construct

SPECIALISTS = [
    "financial",
    "rights_clearance",
    "talent_guild_compliance",
    "regulatory_compliance",
    "risk_strategist",
    "handwriting_analyzer",
]

# Colours for per-specialist lines
SPECIALIST_COLORS = {
    "financial": "#1f77b4",
    "rights_clearance": "#ff7f0e",
    "talent_guild_compliance": "#2ca02c",
    "regulatory_compliance": "#d62728",
    "risk_strategist": "#9467bd",
    "handwriting_analyzer": "#8c564b",
}


class DashboardStack(Stack):
    """CloudWatch operational dashboard for MediaContracts pipeline."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        deployment_id: str,
        stack_suffix: str,
        deployment_tags: dict[str, str],
        specialist_lambdas: dict[str, lambda_.Function],
        jobs_table_name: str,
        orchestrator_runtime_id: str,
        orchestrator_log_group: logs.LogGroup,
        gateway=None,
        gateway_log_group: logs.LogGroup | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.deployment_id = deployment_id
        self.deployment_tags = deployment_tags
        self._apply_common_tags()

        widgets: list[cw.IWidget] = []

        # ── Row 1: Job Health ──────────────────────────────────────

        widgets.append(
            cw.TextWidget(
                markdown="## Job Health",
                width=24,
                height=1,
            )
        )

        # Orchestrator invocations
        orch_invocations = cw.Metric(
            namespace="AWS/BedrockAgentCore",
            metric_name="InvokeAgentRuntime",
            dimensions_map={"AgentRuntimeId": orchestrator_runtime_id},
            statistic="Sum",
            period=Duration.minutes(5),
            label="Orchestrator Invocations",
        )

        orch_errors = cw.Metric(
            namespace="AWS/BedrockAgentCore",
            metric_name="InvokeAgentRuntimeErrors",
            dimensions_map={"AgentRuntimeId": orchestrator_runtime_id},
            statistic="Sum",
            period=Duration.minutes(5),
            label="Orchestrator Errors",
            color=cw.Color.RED,
        )

        widgets.append(
            cw.GraphWidget(
                title="Orchestrator Invocations vs Errors",
                left=[orch_invocations],
                right=[orch_errors],
                width=12,
                height=6,
                period=Duration.minutes(5),
            )
        )

        # DynamoDB job status counts via metric math
        # Counts items with status=COMPLETE and status=FAILED from the GSI
        ddb_reads = cw.Metric(
            namespace="AWS/DynamoDB",
            metric_name="ConsumedReadCapacityUnits",
            dimensions_map={"TableName": jobs_table_name},
            statistic="Sum",
            period=Duration.minutes(5),
            label="DynamoDB Reads",
        )
        ddb_writes = cw.Metric(
            namespace="AWS/DynamoDB",
            metric_name="ConsumedWriteCapacityUnits",
            dimensions_map={"TableName": jobs_table_name},
            statistic="Sum",
            period=Duration.minutes(5),
            label="DynamoDB Writes",
        )

        widgets.append(
            cw.GraphWidget(
                title="DynamoDB Jobs Table Activity",
                left=[ddb_reads, ddb_writes],
                width=12,
                height=6,
            )
        )

        # ── Row 2: Gateway Health ──────────────────────────────────

        if gateway is not None:
            widgets.append(
                cw.TextWidget(
                    markdown="## Gateway Health",
                    width=24,
                    height=1,
                )
            )

            widgets.append(
                cw.GraphWidget(
                    title="Gateway Invocations & Errors",
                    left=[
                        gateway.metric_invocations(
                            period=Duration.minutes(5),
                            statistic="Sum",
                            label="Invocations",
                        ),
                    ],
                    right=[
                        gateway.metric_system_errors(
                            period=Duration.minutes(5),
                            statistic="Sum",
                            label="System Errors",
                            color=cw.Color.RED,
                        ),
                        gateway.metric_user_errors(
                            period=Duration.minutes(5),
                            statistic="Sum",
                            label="User Errors",
                            color=cw.Color.ORANGE,
                        ),
                        gateway.metric_throttles(
                            period=Duration.minutes(5),
                            statistic="Sum",
                            label="Throttles",
                        ),
                    ],
                    width=12,
                    height=6,
                )
            )

            widgets.append(
                cw.GraphWidget(
                    title="Gateway Latency & Duration (ms)",
                    left=[
                        gateway.metric_latency(
                            period=Duration.minutes(5),
                            statistic="p50",
                            label="Latency p50",
                        ),
                        gateway.metric_latency(
                            period=Duration.minutes(5),
                            statistic="p95",
                            label="Latency p95",
                        ),
                        gateway.metric_duration(
                            period=Duration.minutes(5),
                            statistic="p50",
                            label="Duration p50",
                        ),
                        gateway.metric_duration(
                            period=Duration.minutes(5),
                            statistic="p95",
                            label="Duration p95",
                        ),
                    ],
                    right=[
                        gateway.metric_target_execution_time(
                            period=Duration.minutes(5),
                            statistic="p95",
                            label="Target Exec p95",
                            color="#9467bd",
                        ),
                    ],
                    width=12,
                    height=6,
                )
            )

            # Gateway error alarm
            cw.Alarm(
                self,
                "GatewaySystemErrorAlarm",
                alarm_name=f"media-contracts-gateway-system-errors-{deployment_id}-{stack_suffix}",
                alarm_description="AgentCore Gateway system errors (5xx)",
                metric=gateway.metric_system_errors(
                    period=Duration.minutes(5), statistic="Sum"
                ),
                threshold=3,
                evaluation_periods=2,
                comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            )

        if gateway_log_group is not None:
            widgets.append(
                cw.LogQueryWidget(
                    title="Gateway Recent Requests",
                    log_group_names=[gateway_log_group.log_group_name],
                    query_lines=[
                        "fields @timestamp, body.log, body.isError, trace_id, span_id",
                        "sort @timestamp desc",
                        "limit 20",
                    ],
                    view=cw.LogQueryVisualizationType.TABLE,
                    width=24,
                    height=6,
                )
            )

        # ── Row 3: Specialist Duration ─────────────────────────────

        widgets.append(
            cw.TextWidget(
                markdown="## Specialist Lambda Performance",
                width=24,
                height=1,
            )
        )

        # p95 duration per specialist
        p95_metrics = []
        for specialist, fn in specialist_lambdas.items():
            p95_metrics.append(
                cw.Metric(
                    namespace="AWS/Lambda",
                    metric_name="Duration",
                    dimensions_map={"FunctionName": fn.function_name},
                    statistic="p95",
                    period=Duration.minutes(5),
                    label=f"{specialist} p95",
                    color=SPECIALIST_COLORS.get(specialist),
                )
            )

        widgets.append(
            cw.GraphWidget(
                title="Specialist Duration p95 (ms)",
                left=p95_metrics,
                width=12,
                height=6,
            )
        )

        # Error count per specialist
        error_metrics = []
        for specialist, fn in specialist_lambdas.items():
            error_metrics.append(
                cw.Metric(
                    namespace="AWS/Lambda",
                    metric_name="Errors",
                    dimensions_map={"FunctionName": fn.function_name},
                    statistic="Sum",
                    period=Duration.minutes(5),
                    label=f"{specialist} errors",
                    color=SPECIALIST_COLORS.get(specialist),
                )
            )

        widgets.append(
            cw.GraphWidget(
                title="Specialist Errors",
                left=error_metrics,
                width=12,
                height=6,
            )
        )

        # ── Row 3: Throughput ──────────────────────────────────────

        widgets.append(
            cw.TextWidget(
                markdown="## Pipeline Throughput",
                width=24,
                height=1,
            )
        )

        invocation_metrics = []
        for specialist, fn in specialist_lambdas.items():
            invocation_metrics.append(
                cw.Metric(
                    namespace="AWS/Lambda",
                    metric_name="Invocations",
                    dimensions_map={"FunctionName": fn.function_name},
                    statistic="Sum",
                    period=Duration.minutes(5),
                    label=specialist,
                    color=SPECIALIST_COLORS.get(specialist),
                )
            )

        widgets.append(
            cw.GraphWidget(
                title="Specialist Invocations",
                left=invocation_metrics,
                width=12,
                height=6,
            )
        )

        # Throttles
        throttle_metrics = []
        for specialist, fn in specialist_lambdas.items():
            throttle_metrics.append(
                cw.Metric(
                    namespace="AWS/Lambda",
                    metric_name="Throttles",
                    dimensions_map={"FunctionName": fn.function_name},
                    statistic="Sum",
                    period=Duration.minutes(5),
                    label=f"{specialist} throttles",
                    color=SPECIALIST_COLORS.get(specialist),
                )
            )

        widgets.append(
            cw.GraphWidget(
                title="Lambda Throttles",
                left=throttle_metrics,
                width=12,
                height=6,
            )
        )

        # ── Row 4: End-to-end duration & mode split ───────────────

        widgets.append(
            cw.TextWidget(
                markdown="## End-to-End Job Metrics",
                width=24,
                height=1,
            )
        )

        # Job duration by mode
        duration_agent = cw.Metric(
            namespace="MediaContracts/Pipeline",
            metric_name="JobDuration",
            dimensions_map={"Mode": "agent"},
            statistic="p95",
            period=Duration.minutes(5),
            label="Duration p95 — agent mode",
            color="#1f77b4",
        )
        duration_user = cw.Metric(
            namespace="MediaContracts/Pipeline",
            metric_name="JobDuration",
            dimensions_map={"Mode": "user"},
            statistic="p95",
            period=Duration.minutes(5),
            label="Duration p95 — user mode",
            color="#ff7f0e",
        )

        widgets.append(
            cw.GraphWidget(
                title="End-to-End Job Duration p95 (seconds)",
                left=[duration_agent, duration_user],
                width=12,
                height=6,
            )
        )

        # Agent mode vs user mode job counts
        jobs_agent = cw.Metric(
            namespace="MediaContracts/Pipeline",
            metric_name="JobCompleted",
            dimensions_map={"Mode": "agent"},
            statistic="Sum",
            period=Duration.minutes(5),
            label="Completed — agent mode",
            color="#2ca02c",
        )
        jobs_user = cw.Metric(
            namespace="MediaContracts/Pipeline",
            metric_name="JobCompleted",
            dimensions_map={"Mode": "user"},
            statistic="Sum",
            period=Duration.minutes(5),
            label="Completed — user mode",
            color="#9467bd",
        )
        jobs_failed_agent = cw.Metric(
            namespace="MediaContracts/Pipeline",
            metric_name="JobFailed",
            dimensions_map={"Mode": "agent"},
            statistic="Sum",
            period=Duration.minutes(5),
            label="Failed — agent mode",
            color=cw.Color.RED,
        )
        jobs_failed_user = cw.Metric(
            namespace="MediaContracts/Pipeline",
            metric_name="JobFailed",
            dimensions_map={"Mode": "user"},
            statistic="Sum",
            period=Duration.minutes(5),
            label="Failed — user mode",
            color="#d62728",
        )

        widgets.append(
            cw.GraphWidget(
                title="Jobs Completed vs Failed by Mode",
                left=[jobs_agent, jobs_user],
                right=[jobs_failed_agent, jobs_failed_user],
                width=12,
                height=6,
            )
        )

        # ── Row 5: Cost & specialists ──────────────────────────────

        widgets.append(
            cw.TextWidget(
                markdown="## Cost & Specialist Usage",
                width=24,
                height=1,
            )
        )

        cost_agent = cw.Metric(
            namespace="MediaContracts/Pipeline",
            metric_name="EstimatedCostUSD",
            dimensions_map={"Mode": "agent"},
            statistic="Sum",
            period=Duration.minutes(60),
            label="Estimated cost — agent mode ($/hr)",
            color="#1f77b4",
        )
        cost_user = cw.Metric(
            namespace="MediaContracts/Pipeline",
            metric_name="EstimatedCostUSD",
            dimensions_map={"Mode": "user"},
            statistic="Sum",
            period=Duration.minutes(60),
            label="Estimated cost — user mode ($/hr)",
            color="#ff7f0e",
        )

        widgets.append(
            cw.GraphWidget(
                title="Estimated Bedrock Cost (USD/hr, approximate)",
                left=[cost_agent, cost_user],
                width=12,
                height=6,
            )
        )

        specialists_agent = cw.Metric(
            namespace="MediaContracts/Pipeline",
            metric_name="SpecialistsInvoked",
            dimensions_map={"Mode": "agent"},
            statistic="Average",
            period=Duration.minutes(5),
            label="Avg specialists — agent mode",
            color="#1f77b4",
        )
        specialists_user = cw.Metric(
            namespace="MediaContracts/Pipeline",
            metric_name="SpecialistsInvoked",
            dimensions_map={"Mode": "user"},
            statistic="Average",
            period=Duration.minutes(5),
            label="Avg specialists — user mode",
            color="#ff7f0e",
        )

        widgets.append(
            cw.GraphWidget(
                title="Average Specialists Invoked per Job",
                left=[specialists_agent, specialists_user],
                width=12,
                height=6,
            )
        )

        # ── Row 6: Alarms summary ──────────────────────────────────

        widgets.append(
            cw.TextWidget(
                markdown="## Alarms",
                width=24,
                height=1,
            )
        )

        # High error rate alarm per specialist
        for specialist, fn in specialist_lambdas.items():
            alarm = cw.Alarm(
                self,
                f"{specialist.title().replace('_', '')}ErrorAlarm",
                alarm_name=f"media-contracts-{specialist.replace('_', '-')}-errors-{deployment_id}-{stack_suffix}",
                alarm_description=f"High error rate for {specialist} specialist",
                metric=cw.Metric(
                    namespace="AWS/Lambda",
                    metric_name="Errors",
                    dimensions_map={"FunctionName": fn.function_name},
                    statistic="Sum",
                    period=Duration.minutes(5),
                ),
                threshold=3,
                evaluation_periods=2,
                comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
            )
            widgets.append(
                cw.AlarmWidget(
                    alarm=alarm,
                    title=f"{specialist} errors",
                    width=4,
                    height=3,
                )
            )

        # ── Row 7: Orchestrator Agent Loop Visibility (Logs Insights) ──

        widgets.append(
            cw.TextWidget(
                markdown="## Orchestrator Agent Loop",
                width=24,
                height=1,
            )
        )

        widgets.append(
            cw.LogQueryWidget(
                title="Model Calls per Job",
                log_group_names=[orchestrator_log_group.log_group_name],
                query_lines=[
                    'filter event = "after_invocation" and agent = "orchestrator"',
                    "stats max(model_calls) as model_calls by job",
                    "sort model_calls desc",
                    "limit 20",
                ],
                view=cw.LogQueryVisualizationType.BAR,
                width=12,
                height=6,
            )
        )

        widgets.append(
            cw.LogQueryWidget(
                title="Tool Call Latency Breakdown (seconds)",
                log_group_names=[orchestrator_log_group.log_group_name],
                query_lines=[
                    'filter event = "after_tool_call" and agent = "orchestrator"',
                    "parse elapsed /(?<elapsed_num>[\\d.]+)/",
                    "stats avg(elapsed_num) as avg_s, pct(elapsed_num, 95) as p95_s, count(*) as calls by tool",
                    "sort p95_s desc",
                ],
                view=cw.LogQueryVisualizationType.TABLE,
                width=12,
                height=6,
            )
        )

        # ── Row 8: Pipeline Step Waterfall (Logs Insights) ─────────

        widgets.append(
            cw.TextWidget(
                markdown="## Pipeline Step Waterfall",
                width=24,
                height=1,
            )
        )

        widgets.append(
            cw.LogQueryWidget(
                title="Average Time per Pipeline Step (seconds)",
                log_group_names=[orchestrator_log_group.log_group_name],
                query_lines=[
                    "filter ispresent(step) and ispresent(elapsed)",
                    "parse elapsed /(?<elapsed_num>[\\d.]+)/",
                    "stats avg(elapsed_num) as avg_s, pct(elapsed_num, 95) as p95_s, count(*) as samples by step",
                    "sort avg_s desc",
                ],
                view=cw.LogQueryVisualizationType.TABLE,
                width=24,
                height=6,
            )
        )

        # ── Row 9: Model Call Efficiency (Logs Insights) ───────────

        widgets.append(
            cw.TextWidget(
                markdown="## Model Call Efficiency",
                width=24,
                height=1,
            )
        )

        widgets.append(
            cw.LogQueryWidget(
                title="Stop Reason Distribution",
                log_group_names=[orchestrator_log_group.log_group_name],
                query_lines=[
                    'filter event = "after_model_call" and agent = "orchestrator" and ispresent(stop_reason)',
                    "stats count(*) as cnt by stop_reason",
                    "sort cnt desc",
                ],
                view=cw.LogQueryVisualizationType.BAR,
                width=12,
                height=6,
            )
        )

        widgets.append(
            cw.LogQueryWidget(
                title="Model Call Duration Trend (seconds)",
                log_group_names=[orchestrator_log_group.log_group_name],
                query_lines=[
                    'filter event = "after_model_call" and agent = "orchestrator"',
                    "parse elapsed /(?<elapsed_num>[\\d.]+)/",
                    "stats avg(elapsed_num) as avg_s, pct(elapsed_num, 95) as p95_s by bin(5m)",
                ],
                view=cw.LogQueryVisualizationType.LINE,
                width=12,
                height=6,
            )
        )

        # ── Row 10: Error Drill-down (Logs Insights) ───────────────

        widgets.append(
            cw.TextWidget(
                markdown="## Error Drill-down",
                width=24,
                height=1,
            )
        )

        widgets.append(
            cw.LogQueryWidget(
                title="Recent Tool Call Failures",
                log_group_names=[orchestrator_log_group.log_group_name],
                query_lines=[
                    'filter event = "after_tool_call" and status = "error"',
                    "display @timestamp, job, tool, message",
                    "sort @timestamp desc",
                    "limit 20",
                ],
                view=cw.LogQueryVisualizationType.TABLE,
                width=24,
                height=6,
            )
        )

        # ── Build dashboard ────────────────────────────────────────
        self.dashboard = cw.Dashboard(
            self,
            "MediaContractsDashboard",
            dashboard_name=f"MediaContracts-{deployment_id}-{stack_suffix}",
            widgets=[widgets],  # single row array — CW lays out by width
        )

        # ── Alarms — orchestrator runtime ──────────────────────────
        cw.Alarm(
            self,
            "OrchestratorErrorAlarm",
            alarm_name=f"media-contracts-orchestrator-errors-{deployment_id}-{stack_suffix}",
            alarm_description="Orchestrator AgentCore Runtime invocation errors",
            metric=orch_errors,
            threshold=3,
            evaluation_periods=2,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
        )

        # ── Alarms — DynamoDB jobs table ───────────────────────────
        cw.Alarm(
            self,
            "DynamoDBSystemErrorsAlarm",
            alarm_name=f"media-contracts-dynamodb-system-errors-{deployment_id}-{stack_suffix}",
            alarm_description="DynamoDB system errors on jobs table",
            metric=cw.Metric(
                namespace="AWS/DynamoDB",
                metric_name="SystemErrors",
                dimensions_map={"TableName": jobs_table_name},
                statistic="Sum",
                period=Duration.minutes(5),
            ),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
        )

        cw.Alarm(
            self,
            "DynamoDBThrottledRequestsAlarm",
            alarm_name=f"media-contracts-dynamodb-throttles-{deployment_id}-{stack_suffix}",
            alarm_description="DynamoDB throttled requests on jobs table",
            metric=cw.Metric(
                namespace="AWS/DynamoDB",
                metric_name="ThrottledRequests",
                dimensions_map={"TableName": jobs_table_name},
                statistic="Sum",
                period=Duration.minutes(5),
            ),
            threshold=5,
            evaluation_periods=2,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
        )

        # ── Alarms — agent loop health (metric filters on logs) ───

        # High model call count — agent may be looping
        high_model_calls_filter = logs.MetricFilter(
            self,
            "HighModelCallsFilter",
            log_group=orchestrator_log_group,
            filter_pattern=logs.FilterPattern.all(
                logs.FilterPattern.string_value("$.event", "=", "after_invocation"),
                logs.FilterPattern.string_value("$.agent", "=", "orchestrator"),
                logs.FilterPattern.number_value("$.model_calls", ">", 0),
            ),
            metric_namespace="MediaContracts/AgentLoop",
            metric_name=f"ModelCallsPerInvocation-{deployment_id}-{stack_suffix}",
            metric_value="$.model_calls",
            default_value=0,
        )

        cw.Alarm(
            self,
            "HighModelCallCountAlarm",
            alarm_name=f"media-contracts-high-model-calls-{deployment_id}-{stack_suffix}",
            alarm_description=(
                "Orchestrator agent exceeded 8 model calls in a single invocation — "
                "possible reasoning loop"
            ),
            metric=high_model_calls_filter.metric(
                statistic="Maximum",
                period=Duration.minutes(5),
            ),
            threshold=8,
            evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
        )

        # Tool call failure rate
        tool_failure_filter = logs.MetricFilter(
            self,
            "ToolCallFailureFilter",
            log_group=orchestrator_log_group,
            filter_pattern=logs.FilterPattern.literal(
                '"event=after_tool_call" "status=error"'
            ),
            metric_namespace="MediaContracts/AgentLoop",
            metric_name=f"ToolCallFailures-{deployment_id}-{stack_suffix}",
            metric_value="1",
            default_value=0,
        )

        cw.Alarm(
            self,
            "ToolCallFailureRateAlarm",
            alarm_name=f"media-contracts-tool-call-failures-{deployment_id}-{stack_suffix}",
            alarm_description=(
                "3+ tool call failures in 5 minutes — specialist or gateway issue"
            ),
            metric=tool_failure_filter.metric(
                statistic="Sum",
                period=Duration.minutes(5),
            ),
            threshold=3,
            evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
        )

        CfnOutput(
            self,
            "DashboardName",
            value=self.dashboard.dashboard_name,
            export_name=f"{self.stack_name}-DashboardName",
        )

        CfnOutput(
            self,
            "DashboardUrl",
            value=(
                f"https://{self.region}.console.aws.amazon.com/cloudwatch/home"
                f"?region={self.region}#dashboards:name={self.dashboard.dashboard_name}"
            ),
            description="CloudWatch dashboard URL",
        )

    def _apply_common_tags(self) -> None:
        for k, v in self.deployment_tags.items():
            Tags.of(self).add(k, v)
