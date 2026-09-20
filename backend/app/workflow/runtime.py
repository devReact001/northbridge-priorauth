"""Wires the workflow to the real world: local embeddings, pgvector retrieval, a checkpointer."""

import atexit
import logging
import sys
from functools import lru_cache
from typing import Optional

from ..agents.criteria import GENERAL_POLICY_ID, GENERAL_SECTIONS
from ..config import BACKEND_DIR, settings
from ..mcp_client import McpToolbox
from ..rag import search, store
from ..rag.embedder import get_embedder
from ..rag.reranker import get_reranker
from ..schemas import IntakeResult
from .graph import Deps, build_graph


def make_retrieve_policy(embedder, mode: str, reranker=None):
    """Retrieval decides WHICH policy applies; the whole policy is then handed to the criteria agent.

    The Week 2 eval showed section-level retrieval confuses sibling sections inside the right policy,
    so section-level retrieval never sits on the decision path.
    """

    def retrieve(intake: IntakeResult) -> tuple[Optional[str], list[dict]]:
        query = " ".join(filter(None, [intake.requested_procedure, intake.procedure_code, *intake.diagnoses]))
        if not query.strip():
            return None, []
        with store.connect() as conn:
            hits = search.search(conn, embedder, query, top_k=5, mode=mode, reranker=reranker)
            top = next((h for h in hits if h["policy_id"] != GENERAL_POLICY_ID), None)
            if top is None:
                return None, []
            policy = store.fetch_policy_chunks(conn, top["policy_id"])
            general = [c for c in store.fetch_policy_chunks(conn, GENERAL_POLICY_ID)
                       if c["section"] in GENERAL_SECTIONS]
        return top["policy_id"], policy + general

    return retrieve


def _start_toolbox(name: str, module: str, env: dict) -> Optional[McpToolbox]:
    """Start an MCP server as a child process. If it cannot start, log it and carry on without it, so a
    broken integration never stops the note-only workflow."""
    try:
        toolbox = McpToolbox(name, sys.executable, ["-m", module], env=env, cwd=str(BACKEND_DIR)).start()
    except Exception:  # noqa: BLE001
        logging.getLogger("priorauth").exception("MCP server '%s' did not start; continuing without it", name)
        return None
    atexit.register(toolbox.close)
    return toolbox


def make_ehr_tools() -> Optional[McpToolbox]:
    if not settings.ehr_enabled:
        return None
    env = {"FHIR_SOURCE": settings.fhir_source, "FHIR_DIR": settings.fhir_dir,
           "FHIR_BASE_URL": settings.fhir_base_url, "FHIR_TOKEN": settings.fhir_token}
    return _start_toolbox("fhir", "app.mcp_servers.fhir_server", env)


def make_outbound_tools() -> Optional[McpToolbox]:
    if not settings.outbound_enabled:
        return None
    return _start_toolbox("outbound", "app.mcp_servers.outbound_server", {"OUTBOX_DIR": settings.outbox_dir})


def make_checkpointer():
    if settings.checkpointer == "postgres":
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        pool = ConnectionPool(
            settings.database_url, kwargs={"autocommit": True, "row_factory": dict_row}, open=True
        )
        saver = PostgresSaver(pool)
        saver.setup()  # creates the checkpoint tables if they do not exist
        return saver
    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver()


def persist_view(view: dict) -> bool:
    """Best-effort save of a case and its trace. Returns False (and logs) if the database is unavailable,
    so the review queue keeps working without it."""
    if not settings.database_url:
        return False
    try:
        from . import persist

        with store.connect() as conn:
            persist.ensure_tables(conn)
            persist.save_case(conn, view)
        return True
    except Exception:  # noqa: BLE001
        logging.getLogger("priorauth").exception("Failed to persist case %s", view.get("case_id"))
        return False


@lru_cache(maxsize=1)
def get_workflow():
    embedder = get_embedder("local")
    reranker = get_reranker() if search.STRATEGIES[settings.retrieval_mode].rerank else None
    retrieve = make_retrieve_policy(embedder, settings.retrieval_mode, reranker)
    deps = Deps(retrieve_policy=retrieve, ehr_tools=make_ehr_tools(), outbound_tools=make_outbound_tools())
    return build_graph(deps, make_checkpointer())
