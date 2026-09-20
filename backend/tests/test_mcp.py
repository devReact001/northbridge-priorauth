"""The two MCP servers over real stdio: a child process per server, spoken to with the MCP client."""

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from app.mcp_client import McpToolbox, ToolError  # noqa: E402

BACKEND = str(Path(__file__).resolve().parents[1])


@pytest.fixture(scope="module")
def fhir():
    toolbox = McpToolbox("fhir", sys.executable, ["-m", "app.mcp_servers.fhir_server"], cwd=BACKEND).start()
    yield toolbox
    toolbox.close()


@pytest.fixture()
def outbound(tmp_path):
    toolbox = McpToolbox("outbound", sys.executable, ["-m", "app.mcp_servers.outbound_server"],
                         env={"OUTBOX_DIR": str(tmp_path)}, cwd=BACKEND).start()
    yield toolbox, tmp_path
    toolbox.close()


def test_fhir_server_lists_the_read_only_tools_with_schemas(fhir):
    tools = {t["name"]: t for t in fhir.list_tools()}
    assert set(tools) == {"get_patient", "get_conditions", "get_medications", "get_procedures",
                          "get_exam_findings", "get_imaging_reports", "get_service_requests"}
    assert "patient" in tools["get_procedures"]["input_schema"]["properties"]
    assert tools["get_procedures"]["description"]


def test_fhir_server_returns_facts_built_from_the_chart(fhir):
    result = fhir.call("get_imaging_reports", {"patient": "SYN-04471"})
    assert result["count"] == 2
    assert {f["ref"] for f in result["facts"]} == {"DiagnosticReport/dx-1", "DiagnosticReport/dx-2"}
    assert fhir.call("get_conditions", {"patient": "SYN-99999"})["error"] == "patient_not_found"


def test_outbound_submission_is_idempotent_and_writes_a_claim(outbound):
    toolbox, folder = outbound
    args = dict(case_id="case1", patient="SYN-01203", cpt="73721", icd10=["M25.561"],
                letter="Please approve.", approved_by="Nurse Rao")
    first = toolbox.call("submit_prior_authorization", args)
    second = toolbox.call("submit_prior_authorization", args)
    assert first["status"] == "submitted" and second["status"] == "duplicate"
    assert first["reference"] == second["reference"]
    files = list(folder.glob("*.json"))
    assert len(files) == 1
    record = json.loads(files[0].read_text())
    assert record["approved_by"] == "Nurse Rao"
    claim = record["claim"]
    assert claim["resourceType"] == "Claim" and claim["use"] == "preauthorization"
    assert claim["item"][0]["productOrService"]["coding"][0]["code"] == "73721"


def test_outbound_tools_refuse_bad_input(outbound):
    toolbox, folder = outbound
    good = dict(case_id="case2", patient="SYN-01203", cpt="73721", icd10=["M25.561"], letter="x", approved_by="Nurse Rao")
    for bad in ({"approved_by": ""}, {"cpt": "7372"}, {"icd10": []}, {"letter": " "}, {"case_id": "../evil"}):
        with pytest.raises(ToolError):
            toolbox.call("submit_prior_authorization", {**good, **bad})
    with pytest.raises(ToolError):
        toolbox.call("send_clinician_message", dict(case_id="c3", patient="p", subject="s", body="b", approved_by=""))
    assert list(folder.glob("*.json")) == []


def test_clinician_message_is_idempotent(outbound):
    toolbox, _ = outbound
    args = dict(case_id="case4", patient="SYN-00982", subject="More information needed", body="Please send X.",
                approved_by="Nurse Rao")
    assert toolbox.call("send_clinician_message", args)["status"] == "sent"
    assert toolbox.call("send_clinician_message", args)["status"] == "duplicate"


def test_full_workflow_over_real_mcp_servers(tmp_path):
    """Chart lookup and outbound send both go through child-process MCP servers; the fake Claude plays the agents."""
    from langgraph.checkpoint.memory import MemorySaver

    from app.workflow.graph import Deps, build_graph, resume_case, start_case
    from test_ehr_workflow import ChartLLM
    from test_workflow import NOTE, _criteria, _intake, _policy_chunks, _req

    fixed = _criteria()
    fixed["pathways"][0]["requirements"][1] = _req("Supportive exam finding", "met", "3.2", "McMurray test: positive")
    llm = ChartLLM([[("get_exam_findings", {"patient": "SYN-01203"})]],
                   record_intake=_intake(patient_ref="SYN-01203"), record_criteria=fixed)
    fhir_box = McpToolbox("fhir", sys.executable, ["-m", "app.mcp_servers.fhir_server"], cwd=BACKEND).start()
    out_box = McpToolbox("outbound", sys.executable, ["-m", "app.mcp_servers.outbound_server"],
                         env={"OUTBOX_DIR": str(tmp_path)}, cwd=BACKEND).start()
    try:
        deps = Deps(retrieve_policy=lambda i: ("MP-IMG-002", _policy_chunks()), llm_client=llm, model="test",
                    ehr_tools=fhir_box, outbound_tools=out_box)
        graph = build_graph(deps, MemorySaver())
        view = start_case(graph, NOTE)
        assert view["packet"]["ehr"]["status"] == "ok"
        assert list(tmp_path.glob("*.json")) == []  # nothing leaves before a human approves
        done = resume_case(graph, view["case_id"], {"action": "approve", "reviewer": "Nurse Rao"})
        assert done["dispatch"]["status"] == "submitted"
        sent = json.loads(next(tmp_path.glob("*__submission.json")).read_text())
        assert sent["approved_by"] == "Nurse Rao" and sent["claim"]["patient"]["identifier"]["value"] == "SYN-01203"
    finally:
        fhir_box.close()
        out_box.close()
