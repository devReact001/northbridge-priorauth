"""Week 6: the comparison arithmetic. Pure functions, no model."""

from app.workflow import compare


def _view(rec="likely_meets", pathways=None, notes=0, assess_ms=40000, model="claude-sonnet-4-5"):
    pathways = pathways or [{"cite": "MP-IMG-002 section 3.2", "status": "met"}]
    trace = [
        {"node": "intake", "latency_ms": 5000, "input_tokens": 1000, "output_tokens": 300, "detail": {"model": model}},
        {"node": "policy", "latency_ms": 0, "input_tokens": 0, "output_tokens": 0, "detail": {}},
        {"node": "assess", "latency_ms": assess_ms, "input_tokens": 6000, "output_tokens": 3000, "detail": {"model": model}},
    ]
    return {"recommendation": rec, "trace": trace, "packet": {
        "pathways": pathways, "guardrail_notes": ["x"] * notes,
        "general_requirements": [{"status": "met"}, {"status": "unclear"}]}}


def test_cost_uses_the_price_of_the_model_each_step_ran_on():
    r = compare.run_record("n", 0, _view(), 60000)
    expected = (1000 * 3 + 300 * 15 + 6000 * 3 + 3000 * 15) / 1_000_000
    assert r["cost_usd"] == round(expected, 4)
    assert r["steps"]["assess"]["model"] == "claude-sonnet-4-5"
    assert r["general_met"] == 1 and r["general_total"] == 2


def test_an_unpriced_model_reports_no_cost_instead_of_a_guess():
    assert compare.run_record("n", 0, _view(model="some-new-model"), 1)["cost_usd"] is None
    assert compare.run_record("n", 0, _view(model="some-new-model"), 1, prices={"some-new-model": (1, 1)})["cost_usd"] == 0.0103


def test_agreement_needs_the_same_recommendation_and_the_same_pathway_statuses():
    base = compare.run_record("n", 0, _view(), 1)
    same = compare.run_record("n", 0, _view(), 1)
    other_path = compare.run_record("n", 0, _view(pathways=[{"cite": "MP-IMG-002 section 3.2", "status": "unclear"}]), 1)
    other_rec = compare.run_record("n", 0, _view(rec="needs_more_info"), 1)
    assert compare.agrees(base, same) == (True, True)
    assert compare.agrees(base, other_path) == (True, False)
    assert compare.agrees(base, other_rec) == (False, True)


def test_summary_compares_with_the_reference_and_measures_the_references_own_noise():
    runs = {
        "baseline": [compare.run_record("a", 0, _view(), 70000), compare.run_record("a", 1, _view(rec="needs_more_info"), 72000),
                     compare.run_record("b", 0, _view(), 68000)],
        "split": [compare.run_record("a", 0, _view(assess_ms=20000), 45000), compare.run_record("b", 0, _view(rec="needs_more_info"), 47000),
                  compare.failed_record("b", 1, "boom")],
    }
    base, split = compare.summarize(runs)
    assert base["same_recommendation"] == "0/1" and base["wall_p50_s"] == 70.0, "the baseline disagreed with itself once"
    assert split["same_recommendation"] == "1/2" and split["failed"] == 1
    assert split["assess_p50_s"] == 20.0 and split["wall_p50_s"] == 45.0
    assert "| split |" in compare.markdown([base, split])


def test_differences_name_the_pathway_or_recommendation_that_changed():
    base = compare.run_record("n", 0, _view(), 1)
    changed = compare.run_record("n", 0, _view(rec="needs_more_info", pathways=[{"cite": "MP-IMG-002 section 3.2", "status": "unclear"}]), 1)
    assert compare.differences(base, base) == []
    assert compare.differences(base, changed) == [
        "recommendation likely_meets -> needs_more_info", "pathway MP-IMG-002 section 3.2: met -> unclear"]
