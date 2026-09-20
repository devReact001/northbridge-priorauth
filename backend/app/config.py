from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env lives in the project root, two levels above this file
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5"
    database_url: str = ""
    # Which retrieval strategy the workflow uses to pick a policy (see app/rag/search.py STRATEGIES).
    retrieval_mode: str = "hybrid_w3_rerank"
    # "memory" keeps paused cases in the API process; "postgres" survives restarts.
    checkpointer: str = "memory"
    # Week 4: EHR enrichment through a read-only FHIR MCP server.
    ehr_enabled: bool = True
    fhir_source: str = "bundle"  # "bundle" = synthetic FHIR files in fhir_dir, "http" = a FHIR REST API
    fhir_dir: str = str(BACKEND_DIR / "app" / "data" / "fhir")
    fhir_base_url: str = ""  # for fhir_source=http, e.g. https://hapi.fhir.org/baseR4 (synthetic data only)
    fhir_token: str = ""
    # Week 4: outbound actions (submission, clinician message) through a write-side MCP server, after approval.
    outbound_enabled: bool = True
    outbox_dir: str = str(BACKEND_DIR.parent / "outbox")
    # Week 5: when set, every API route except /health needs this in an X-API-Key header. The Next.js server
    # adds it, so it never reaches a browser. Empty means open, which is fine on localhost only.
    api_key: str = ""
    # Week 6: a different model per step (empty = ANTHROPIC_MODEL), and two switchable ways to make the criteria
    # step faster. Both default to off until scripts/compare_models.py shows they do not change the answers.
    # Week 6: load the embedding and reranker models when the API starts instead of on the first case, and report
    # "not ready" until that is done. Used in Kubernetes; local development can leave it off.
    warmup_on_start: bool = False
    intake_model: str = ""
    ehr_model: str = ""
    assess_model: str = ""
    draft_model: str = ""
    assess_lean: bool = False   # a shorter tool schema, so the model writes fewer tokens
    assess_split: bool = False  # pathways and general requirements in two parallel calls (implies lean)


settings = Settings()
