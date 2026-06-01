"""
Agent Factory — Creates Strands agents for the media contract analysis pipeline.

The pipeline has 6 specialist agents:
  1. extractor       — Parses raw contract into structured extraction
  2. financial       — Analyzes deal economics
  3. rights_clearance — Analyzes IP ownership, clearances, rights scope
  4. talent_guild_compliance — Analyzes talent protections and guild compliance
  5. regulatory_compliance   — Analyzes regulatory obligations
  6. risk_strategist — Synthesizes all findings into risk assessment

Usage:
    from agent_factory import AgentFactory

    factory = AgentFactory(
        agents_dir="media_contracts_agents",
        model_id="us.anthropic.claude-sonnet-4-6",
        tools=[glossary_lookup, read_docx],
    )

    extractor = factory.create("extractor")
    financial = factory.create("financial")
    all_agents = factory.create_all()  # dict[str, Agent]
"""

from __future__ import annotations

from typing import Any

from strands import Agent
from strands.models.bedrock import BedrockModel

from .prompt_loader import PromptLoader


class AgentFactory:
    """Creates configured Strands agents for each specialist in the pipeline."""

    # Agents that receive the raw contract (need read_docx tool)
    _EXTRACTION_AGENTS = {"extractor"}

    def __init__(
        self,
        agents_dir: str = "media_contracts_agents",
        model_id: str = "us.anthropic.claude-sonnet-4-6",
        max_tokens: int = 64000,
        tools: list[Any] | None = None,
        extraction_tools: list[Any] | None = None,
        analysis_tools: list[Any] | None = None,
    ) -> None:
        """
        Args:
            agents_dir: Path to the directory containing agent prompt folders.
            model_id: Bedrock model ID.
            max_tokens: Max output tokens per agent call.
            tools: Default tools for all agents (fallback if specific lists not given).
            extraction_tools: Tools for the extractor agent (needs read_docx).
            analysis_tools: Tools for analysis agents (glossary_lookup, etc.).
        """
        self._loader = PromptLoader(agents_dir)
        self._model_id = model_id
        self._max_tokens = max_tokens
        self._default_tools = tools or []
        self._extraction_tools = extraction_tools or self._default_tools
        self._analysis_tools = analysis_tools or self._default_tools

    def create(
        self,
        agent_name: str,
        model_id: str | None = None,
        max_tokens: int | None = None,
    ) -> Agent:
        """Create a single specialist agent by name.

        Args:
            agent_name: Which agent to create.
            model_id: Override the default model for this agent.
            max_tokens: Override the default max_tokens for this agent.
        """
        prompt = self._loader.load_agent_prompt(agent_name)
        tools = (
            self._extraction_tools
            if agent_name in self._EXTRACTION_AGENTS
            else self._analysis_tools
        )
        model = BedrockModel(
            model_id=model_id or self._model_id,
            max_tokens=max_tokens or self._max_tokens,
        )
        return Agent(
            model=model,
            system_prompt=prompt,
            tools=tools,
        )

    def create_all(self) -> dict[str, Agent]:
        """Create all specialist agents. Returns {agent_name: Agent}."""
        return {name: self.create(name) for name in self._loader.list_agents()}

    def list_agents(self) -> list[str]:
        """List available agent names."""
        return self._loader.list_agents()

    def get_prompt(self, agent_name: str) -> str:
        """Get the full system prompt for an agent (for inspection)."""
        return self._loader.load_agent_prompt(agent_name)

    def __repr__(self) -> str:
        return f"AgentFactory(model={self._model_id}, agents={self.list_agents()})"
