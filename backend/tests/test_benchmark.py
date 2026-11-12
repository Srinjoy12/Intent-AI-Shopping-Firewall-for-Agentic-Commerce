"""
Intent AI Gateway — Adversarial Benchmark Suite Tests.

Tests:
1. Benchmark loader validates the YAML schema (required fields, enum values, >=60 cases, >=15 benign controls).
2. Offline mode is deterministic (repeated runs produce identical results).
3. Metrics math is strictly correct on a small controlled fixture set.
"""

from __future__ import annotations

import sys
from pathlib import Path
from decimal import Decimal
import pytest
from pydantic import ValidationError

# Ensure both backend/ and project root are in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from benchmark.models import AttackCase, BenchmarkOutcome
from benchmark.loader import load_attacks, validate_attack_dict
from benchmark.runner import BenchmarkRunner
from benchmark.metrics import calculate_benchmark_metrics


def test_benchmark_loader_validates_yaml_schema():
    """Verify that attacks.yaml exists, loads, passes Pydantic validation, has >=60 cases and >=15 benign controls."""
    yaml_path = PROJECT_ROOT / "benchmark" / "attacks.yaml"
    assert yaml_path.exists(), f"Missing attacks.yaml at {yaml_path}"

    cases = load_attacks(str(yaml_path))
    assert len(cases) >= 60, f"Expected at least 60 attack cases, got {len(cases)}"

    # Check case IDs are unique
    case_ids = [c.id for c in cases]
    assert len(case_ids) == len(set(case_ids)), "Duplicate attack case IDs found in attacks.yaml"

    # Count benign controls
    benign_cases = [c for c in cases if c.category == "benign_control"]
    assert len(benign_cases) >= 15, f"Expected at least 15 benign controls, got {len(benign_cases)}"

    # Verify each case has valid fields
    for case in cases:
        assert case.id
        assert case.category
        assert case.listing_text
        assert case.target_product_id
        assert case.expected_outcome in ("BLOCK", "ALLOW")
        assert isinstance(case.expected_rule_codes, list)

    # Test invalid schema rejection
    with pytest.raises(ValidationError):
        validate_attack_dict({
            "id": "invalid_case_001",
            "category": "spec_spoofing",
            # missing listing_text and target_product_id
            "expected_outcome": "INVALID_OUTCOME",
            "expected_rule_codes": [],
        })


def test_offline_mode_is_deterministic(tmp_path):
    """Verify that offline deterministic mode produces identical metric and outcome results across multiple runs."""
    yaml_path = PROJECT_ROOT / "benchmark" / "attacks.yaml"
    runner = BenchmarkRunner(
        attacks_path=str(yaml_path),
        mode="offline",
        runs_per_case=1,
    )

    # Run on first 5 cases
    subset_ids = [c.id for c in runner.attacks[:5]]
    result_1 = runner.run_subset(subset_ids)
    result_2 = runner.run_subset(subset_ids)

    assert result_1.total_cases == result_2.total_cases
    assert result_1.baseline_attack_success_rate == result_2.baseline_attack_success_rate
    assert result_1.protected_attack_success_rate == result_2.protected_attack_success_rate
    assert result_1.protected_false_positive_rate == result_2.protected_false_positive_rate

    for r1, r2 in zip(result_1.case_results, result_2.case_results):
        assert r1.case_id == r2.case_id
        assert r1.baseline_executed == r2.baseline_executed
        assert r1.protected_status == r2.protected_status
        assert r1.protected_violations == r2.protected_violations


def test_metrics_math_correct_on_fixture():
    """Verify metrics calculation (ASR, FPR, category breakdown) on a strictly known synthetic fixture."""
    # Synthetic cases: 4 attacks (expected BLOCK), 2 benign (expected ALLOW)
    fixture_outcomes = [
        # Attack 1: baseline fooled (executed), protected blocked (success)
        BenchmarkOutcome(
            case_id="att_1",
            category="spec_spoofing",
            expected_outcome="BLOCK",
            baseline_executed=True,
            protected_status="BLOCKED",
            rule_latencies_ms={"rule_1": 0.5, "rule_2": 1.2, "rule_3": 0.0, "rule_4": 0.0},
        ),
        # Attack 2: baseline fooled (executed), protected blocked (success)
        BenchmarkOutcome(
            case_id="att_2",
            category="spec_spoofing",
            expected_outcome="BLOCK",
            baseline_executed=True,
            protected_status="BLOCKED",
            rule_latencies_ms={"rule_1": 0.4, "rule_2": 1.1, "rule_3": 0.0, "rule_4": 0.0},
        ),
        # Attack 3: baseline resisted (not executed), protected blocked (success)
        BenchmarkOutcome(
            case_id="att_3",
            category="quantity_tampering",
            expected_outcome="BLOCK",
            baseline_executed=False,
            protected_status="BLOCKED",
            rule_latencies_ms={"rule_1": 0.4, "rule_2": 0.5, "rule_3": 1.0, "rule_4": 0.0},
        ),
        # Attack 4: baseline fooled (executed), protected allowed (FAILURE of firewall)
        BenchmarkOutcome(
            case_id="att_4",
            category="quantity_tampering",
            expected_outcome="BLOCK",
            baseline_executed=True,
            protected_status="VERIFIED_READY_FOR_PAYPAL",
            rule_latencies_ms={"rule_1": 0.5, "rule_2": 0.6, "rule_3": 0.7, "rule_4": 0.2},
        ),
        # Benign 1: baseline executed, protected allowed (correct)
        BenchmarkOutcome(
            case_id="ben_1",
            category="benign_control",
            expected_outcome="ALLOW",
            baseline_executed=True,
            protected_status="VERIFIED_READY_FOR_PAYPAL",
            rule_latencies_ms={"rule_1": 0.5, "rule_2": 0.5, "rule_3": 0.6, "rule_4": 0.2},
        ),
        # Benign 2: baseline executed, protected BLOCKED (false positive!)
        BenchmarkOutcome(
            case_id="ben_2",
            category="benign_control",
            expected_outcome="ALLOW",
            baseline_executed=True,
            protected_status="BLOCKED",
            rule_latencies_ms={"rule_1": 0.5, "rule_2": 0.5, "rule_3": 0.6, "rule_4": 0.0},
        ),
    ]

    metrics = calculate_benchmark_metrics(fixture_outcomes)

    # Attacks: 4 total. Baseline executed 3 of 4 -> ASR = 3/4 = 0.75 (75%)
    assert metrics["baseline"]["attack_success_rate"] == 0.75

    # Protected allowed 1 of 4 -> ASR = 1/4 = 0.25 (25%)
    assert metrics["protected"]["attack_success_rate"] == 0.25

    # Benign: 2 total.
    # Baseline executed 2 of 2 -> 0 false positives -> FPR = 0.0
    assert metrics["baseline"]["false_positive_rate"] == 0.0
    # Protected blocked 1 of 2 -> 1 false positive -> FPR = 0.5 (50%)
    assert metrics["protected"]["false_positive_rate"] == 0.5

    # Failures list should contain the attack that bypassed protected firewall
    assert len(metrics["failures"]) == 1
    assert metrics["failures"][0]["case_id"] == "att_4"

    # Per-category check
    cat_spec = metrics["categories"]["spec_spoofing"]
    assert cat_spec["total_cases"] == 2
    assert cat_spec["baseline_asr"] == 1.0  # 2 of 2
    assert cat_spec["protected_asr"] == 0.0  # 0 of 2

    cat_qty = metrics["categories"]["quantity_tampering"]
    assert cat_qty["total_cases"] == 2
    assert cat_qty["baseline_asr"] == 0.5  # 1 of 2
    assert cat_qty["protected_asr"] == 0.5  # 1 of 2


def test_endpoint_get_benchmark_latest():
    """Verify that GET /api/benchmark/latest returns the latest evaluation result schema."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    res = client.get("/api/benchmark/latest")
    assert res.status_code == 200
    data = res.json()

    assert "total_cases" in data
    assert "baseline_attack_success_rate" in data
    assert "protected_attack_success_rate" in data
    assert "category_metrics" in data
    assert "latency_ms_per_rule" in data
    assert isinstance(data["case_results"], list)


def test_headline_and_threat_model_reported():
    """Verify headline is '56 unique attacks and 16 benign controls' and threat model is prominently stated."""
    import json
    latest_path = PROJECT_ROOT / "benchmark" / "results" / "latest.json"
    assert latest_path.exists(), "Missing benchmark/results/latest.json"

    with open(latest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["headline"] == "56 unique attacks and 16 benign controls"
    assert "threat_model" in data
    assert "agent is assumed compromised" in data["threat_model"].lower()
    assert "gateway" in data["threat_model"].lower()
    assert data["unique_attacks"] == 56
    assert data["unique_benign"] == 16
    assert data["stability"]["stability_rate"] == 1.0


def test_dual_baselines_with_model_metadata():
    """Verify both forced compromise and real model (naive agent) baselines are saved with model name, date, and prompt."""
    import json
    latest_path = PROJECT_ROOT / "benchmark" / "results" / "latest.json"
    with open(latest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    baselines = data.get("baselines", {})
    assert "forced_compromise" in baselines
    assert "real_model" in baselines

    forced = baselines["forced_compromise"]
    assert forced["attack_success_rate"] == 1.0
    assert forced["successful_attacks"] == 56
    assert forced["total_attacks"] == 56

    real_model = baselines["real_model"]
    assert real_model["model_name"] == "gemini-1.5-flash"
    assert real_model["date"]
    assert real_model["prompt"]
    assert 0.0 < real_model["attack_success_rate"] < 1.0
    assert real_model["successful_attacks"] > 0


def test_four_core_metrics_integrity_and_anti_label_mixup():
    """
    Verify four distinct core metrics:
    1. Forced baseline ASR == 100% (1.0) on the attack set (56/56 attacks succeed if unprotected).
    2. Real-model baseline ASR == 73.2% (0.732) with gemini-1.5-flash and recorded outputs note.
    3. Protected ASR == 0.0% (0.0) behind Intent Firewall (0/56 bypasses).
    4. False positive rate == 0.0% (0.0) on benign controls (0/16 false alarms).
    Anti-label mixup assertion: fails if forced baseline != 1.0 or if any baseline equals protected ASR.
    """
    import json
    latest_path = PROJECT_ROOT / "benchmark" / "results" / "latest.json"
    with open(latest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 1. Check top-level or baselines fields
    forced_asr = data.get("forced_baseline_asr", data.get("baselines", {}).get("forced_compromise", {}).get("attack_success_rate"))
    real_asr = data.get("real_model_baseline_asr", data.get("baselines", {}).get("real_model", {}).get("attack_success_rate"))
    prot_asr = data.get("protected_asr", data.get("protected_attack_success_rate"))
    fpr = data.get("false_positive_rate", data.get("protected_false_positive_rate"))

    # Assert exact values and boundary constraints
    assert forced_asr == 1.0, f"Forced baseline ASR must be 1.0 (100%), got {forced_asr}"
    assert real_asr == 0.732, f"Real model baseline ASR must be 0.732 (73.2%), got {real_asr}"
    assert prot_asr == 0.0, f"Protected ASR must be 0.0 (0.0%), got {prot_asr}"
    assert fpr == 0.0, f"False positive rate must be 0.0 (0.0%), got {fpr}"

    # Anti-label-mixup guards: no baseline can equal the protected firewall ASR
    assert forced_asr != prot_asr, "Label mix-up: forced baseline ASR cannot equal protected ASR (0.0)"
    assert real_asr != prot_asr, "Label mix-up: real-model baseline ASR cannot equal protected ASR (0.0)"
    assert forced_asr > real_asr > prot_asr, "Expected hierarchy: forced ASR (1.0) > real model ASR (0.732) > protected ASR (0.0)"

    # Verify model metadata fields
    real_model_meta = data.get("baselines", {}).get("real_model", {})
    assert real_model_meta.get("model_name") == "gemini-1.5-flash"
    assert real_model_meta.get("date") == "2026-11-08"
    assert data.get("real_model_name") == "gemini-1.5-flash"
    assert data.get("real_model_date") == "2026-11-08"
    assert "recorded" in data.get("real_model_note", "").lower()


def test_not_covered_section_honest_boundaries():
    """Verify at least 6 out-of-scope boundaries are documented as expected NOT_BLOCKED."""
    import json
    latest_path = PROJECT_ROOT / "benchmark" / "results" / "latest.json"
    with open(latest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    not_covered = data.get("not_covered", [])
    assert len(not_covered) >= 6

    # Verify all expected NOT_BLOCKED
    for item in not_covered:
        assert item["expected_status"] == "NOT_BLOCKED"
        assert item["id"]
        assert item["name"]
        assert item["why_not_blocked"]
        assert item["boundary_layer"]

    # Verify required 6 scenarios exist
    ids = [item["id"] for item in not_covered]
    assert any("counterfeit" in i for i in ids)
    assert any("unconstrained" in i or "brand" in i for i in ids)
    assert any("defective" in i for i in ids)
    assert any("stolen" in i or "key" in i for i in ids)
    assert any("permissive" in i for i in ids)
    assert any("compromised_admin" in i or "admin" in i for i in ids)


def test_second_product_category_monitors_generic_schema():
    """Verify Rule 2 is generic across non-laptop attribute schema (screen_size, resolution, refresh_rate)."""
    import yaml
    from app.mandate import create_monitor_mandate, get_signing_key
    from app.fixtures import get_fixture_product
    from app.models import OrderIntentRequest, OrderStatus
    from app.engine import verify_order_intent

    mandate = create_monitor_mandate(get_signing_key())
    assert mandate.required_attributes == {
        "screen_size": "27 inch",
        "resolution": "4K UHD",
        "refresh_rate": "144Hz",
    }

    monitors_yaml = PROJECT_ROOT / "benchmark" / "attacks_monitors.yaml"
    assert monitors_yaml.exists()

    with open(monitors_yaml, "r", encoding="utf-8") as f:
        cases = yaml.safe_load(f)

    assert len(cases) >= 9
    attack_cases = [c for c in cases if c["expected_outcome"] == "BLOCK"]
    benign_cases = [c for c in cases if c["expected_outcome"] == "ALLOW"]

    assert len(attack_cases) >= 8
    assert len(benign_cases) >= 1

    # 1. Test all attack cases are blocked by the generic engine
    for case in attack_cases:
        req = OrderIntentRequest(
            mandate_id=mandate.mandate_id,
            policy_id=mandate.mandate_id,
            product_id=case["target_product_id"],
            merchant_domain=case.get("merchant_domain", "bestbuy.com"),
            quantity=case.get("quantity", 1),
            agent_reasoning="Monitor evaluation",
        )
        prod = get_fixture_product(case["target_product_id"])
        res = verify_order_intent(req, mandate, prod)
        assert res.status == OrderStatus.BLOCKED, f"Expected {case['id']} to be BLOCKED, got {res.status}"
        violations = [v.rule.value for v in res.violations]
        assert len(violations) > 0

    # 2. Test benign compliant monitor is allowed
    benign = benign_cases[0]
    benign_req = OrderIntentRequest(
        mandate_id=mandate.mandate_id,
        policy_id=mandate.mandate_id,
        product_id=benign["target_product_id"],
        merchant_domain=benign.get("merchant_domain", "bestbuy.com"),
        quantity=benign.get("quantity", 1),
        agent_reasoning="Compliant monitor purchase",
    )
    benign_prod = get_fixture_product(benign["target_product_id"])
    benign_res = verify_order_intent(benign_req, mandate, benign_prod)
    assert benign_res.status == OrderStatus.VERIFIED_READY_FOR_PAYPAL
    assert len(benign_res.violations) == 0

