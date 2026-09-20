"""Week 6: the deployment files agree with each other and with the code. No cluster or Docker needed; these catch
the mistakes that otherwise show up as a pod that will not start."""

import re
from pathlib import Path

import pytest

from app.config import Settings
from app.rag.embedder import LocalEmbedder
from app.rag.reranker import CrossEncoderReranker

yaml = pytest.importorskip("yaml")
ROOT = Path(__file__).resolve().parents[2]
K8S = ROOT / "k8s"


def load(name: str) -> list[dict]:
    return [d for d in yaml.safe_load_all((K8S / name).read_text(encoding="utf-8")) if d]


def all_docs() -> list[dict]:
    files = [f.name for f in K8S.glob("*.yaml") if f.name != "kustomization.yaml"]
    return [d for f in files for d in load(f)]


def of_kind(kind: str) -> list[dict]:
    return [d for d in all_docs() if d["kind"] == kind]


def containers(doc: dict) -> list[dict]:
    spec = doc["spec"]["template"]["spec"]
    return spec["containers"] + spec.get("initContainers", [])


def test_every_manifest_parses_and_the_kustomization_lists_only_files_that_exist():
    kustomization = load("kustomization.yaml")[0]
    for name in kustomization["resources"]:
        assert (K8S / name).exists(), name
    listed = set(kustomization["resources"])
    on_disk = {f.name for f in K8S.glob("*.yaml")} - {"kustomization.yaml", "ingest-job.yaml"}
    assert listed == on_disk, "every manifest is applied by kustomize, except the ingest Job which is run on purpose"


def test_no_secret_is_committed_and_everything_lives_in_the_northbridge_namespace():
    assert of_kind("Secret") == [], "secrets are created by scripts/k8s-deploy.ps1, never stored in the repository"
    for doc in all_docs():
        if doc["kind"] != "Namespace":
            assert doc["metadata"]["namespace"] == "northbridge", doc["metadata"]["name"]


def test_config_map_keys_are_real_settings():
    known = {name.upper() for name in Settings.model_fields}
    for key in load("config.yaml")[0]["data"]:
        assert key in known, f"{key} is not a setting the API reads, so it would be silently ignored"


def test_secret_references_match_what_the_deploy_script_creates():
    script = (ROOT / "scripts" / "k8s-deploy.ps1").read_text(encoding="utf-8")
    created = set(re.findall(r"--from-literal=([A-Z_]+)=", script))
    used = set()
    for doc in of_kind("Deployment") + of_kind("StatefulSet") + of_kind("Job"):
        for c in containers(doc):
            for env in c.get("env", []):
                ref = (env.get("valueFrom") or {}).get("secretKeyRef")
                if ref:
                    assert ref["name"] == "northbridge-secrets"
                    used.add(ref["key"])
    assert used and used <= created, f"keys used but never created: {used - created}"


def test_database_url_comes_after_the_password_it_expands():
    for doc in [d for d in of_kind("Deployment") + of_kind("Job") if d["metadata"]["name"] in ("api", "ingest")]:
        names = [e["name"] for c in containers(doc) for e in c["env"]]
        assert names.index("POSTGRES_PASSWORD") < names.index("DATABASE_URL"), "$(VAR) only expands earlier variables"


def test_workloads_are_pinned_limited_probed_and_not_root():
    for doc in of_kind("Deployment") + of_kind("StatefulSet") + of_kind("Job"):
        name = doc["metadata"]["name"]
        for c in containers(doc):
            assert not c["image"].endswith(":latest") and ":" in c["image"], f"{name}: pin the image tag"
            assert c["resources"]["requests"] and c["resources"]["limits"]["memory"], name
        if doc["kind"] == "Deployment":
            for c in containers(doc):
                assert c["readinessProbe"] and c["livenessProbe"], name
                assert c["securityContext"]["allowPrivilegeEscalation"] is False, name
                assert c["securityContext"]["capabilities"]["drop"] == ["ALL"], name
            assert doc["spec"]["template"]["spec"]["securityContext"]["runAsNonRoot"] is True, name


def test_the_api_runs_one_replica_and_holds_traffic_until_the_models_are_loaded():
    api = next(d for d in of_kind("Deployment") if d["metadata"]["name"] == "api")
    assert api["spec"]["replicas"] == 1, "a started case runs in one pod's background thread; see docs/case-study.md"
    assert api["spec"]["strategy"]["type"] == "Recreate"
    c = api["spec"]["template"]["spec"]["containers"][0]
    assert c["readinessProbe"]["httpGet"]["path"] == "/ready"
    assert c["livenessProbe"]["httpGet"]["path"] == "/health"
    assert load("config.yaml")[0]["data"]["WARMUP_ON_START"] == "true"


def test_the_api_can_write_its_outbox_where_the_config_says():
    api = next(d for d in of_kind("Deployment") if d["metadata"]["name"] == "api")
    mounts = {m["mountPath"] for m in api["spec"]["template"]["spec"]["containers"][0]["volumeMounts"]}
    assert load("config.yaml")[0]["data"]["OUTBOX_DIR"] in mounts


def test_network_policies_select_labels_the_pods_really_have():
    labels = set()
    for doc in of_kind("Deployment") + of_kind("StatefulSet") + of_kind("Job"):
        labels.add(doc["spec"]["template"]["metadata"]["labels"]["app"])
    for pol in of_kind("NetworkPolicy"):
        for sel in [pol["spec"]["podSelector"]] + [f["podSelector"] for r in pol["spec"].get("ingress", []) for f in r.get("from", [])]:
            for app in (sel.get("matchLabels") or {}).values():
                assert app in labels, f"{pol['metadata']['name']} selects app={app}, which no pod has"
            for expr in sel.get("matchExpressions", []):
                assert set(expr["values"]) <= labels
    assert any(p["spec"]["podSelector"] == {} for p in of_kind("NetworkPolicy")), "a default-deny policy is present"


def test_services_point_at_ports_the_containers_expose():
    exposed = {}
    for doc in of_kind("Deployment") + of_kind("StatefulSet"):
        exposed[doc["spec"]["template"]["metadata"]["labels"]["app"]] = {
            p["containerPort"] for c in containers(doc) for p in c.get("ports", [])}
    for svc in of_kind("Service"):
        app = svc["spec"]["selector"]["app"]
        for port in svc["spec"]["ports"]:
            assert port["targetPort"] in exposed[app], f"service {svc['metadata']['name']} targets an unexposed port"


def test_the_api_image_bakes_in_the_same_models_the_code_loads():
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert LocalEmbedder.name in dockerfile and CrossEncoderReranker.name in dockerfile, \
        "the image would download a model at runtime, which fails with HF_HUB_OFFLINE=1 and no internet"
    assert "HF_HUB_OFFLINE=1" in dockerfile and "USER 10001" in dockerfile


def test_the_ingest_job_reads_pdfs_from_where_the_dockerfile_copies_them():
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    job = load("ingest-job.yaml")[0]
    command = job["spec"]["template"]["spec"]["containers"][0]["command"]
    assert "COPY policies/pdf ./policies/pdf" in dockerfile and "/srv/policies/pdf" in command
    assert (ROOT / "policies" / "pdf").is_dir()


def test_docker_ignore_keeps_secrets_and_virtual_environments_out_of_the_build_context():
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for entry in (".env", "**/.venv", "**/node_modules"):
        assert entry in ignore
    front = (ROOT / "frontend" / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in front and "node_modules" in front


def test_the_web_image_reads_the_backend_address_at_runtime_not_build_time():
    web = next(d for d in of_kind("Deployment") if d["metadata"]["name"] == "web")
    env = {e["name"] for e in web["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert {"API_BASE_URL", "API_KEY"} <= env
    lines = [l for l in (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#")]
    assert not [l for l in lines if l.startswith(("ARG", "ENV")) and "API_" in l], "nothing about the backend is baked into the image"
