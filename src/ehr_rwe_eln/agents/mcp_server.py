"""The OMOP tools as an MCP server, for Claude Code during development.

Runs over stdio: Claude Code starts it as a local process (.mcp.json at the repo root), so
nothing listens on a port and the public demo never serves it (decided 2026-11-21). The tools are
the agent's (agents/workbench.py, same names), reading the database .env points at: the Compose
Postgres locally, with omop_stats built by scripts/build_omop_stats.py --target local.

Run by hand: uv run python -m ehr_rwe_eln.agents.mcp_server
"""

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from ehr_rwe_eln.agents import omop_tools
from ehr_rwe_eln.agents.workbench import _call

server = MCPServer(
    name="omop",
    instructions=(
        "Read-only counts and results from the ehr-rwe-eln OMOP CDM (synthetic Synthea data, "
        "23,421 people). Person counts are per concept, rolled up through descendants; counts "
        "under 11 are suppressed and shown as 'fewer than 11'. No patient-level data."
    ),
)
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)


@server.tool(annotations=READ_ONLY)
def omop_concept_search(text: str, domain: str | None = None, limit: int = 10) -> str:
    """Find OMOP concepts in the data whose name contains text (or whose concept ID is text),
    with how many people have each, counting descendant concepts. Most people first. domain:
    Condition, Drug, Procedure, Measurement, Observation, or Device. limit: 1 to 25."""
    return _call(omop_tools.concept_search, text, domain, limit)


@server.tool(annotations=READ_ONLY)
def omop_concept_count(concept_id: int) -> str:
    """How many people have this concept or any descendant, and how many records."""
    return _call(omop_tools.concept_count, concept_id)


@server.tool(annotations=READ_ONLY)
def tte_results_get(protocol: str | None = None) -> str:
    """The newest target trial emulation results, one protocol or all."""
    return _call(omop_tools.tte_results, protocol)


@server.tool(annotations=READ_ONLY)
def dq_results_get(table: str | None = None, category: str | None = None) -> str:
    """The newest data quality run: checks failed, worst first; optionally one OMOP table or one
    category (Conformance, Completeness, Plausibility)."""
    if category not in (None, "Conformance", "Completeness", "Plausibility"):
        return '{"error": "category must be Conformance, Completeness, or Plausibility"}'
    return _call(omop_tools.dq_results, table, category)


if __name__ == "__main__":
    server.run("stdio")
