"""
Benchmark Data Models for Intent Adversarial Firewall Evaluation.
"""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class AttackCase(BaseModel):
    """
    Represents a single test case from attacks.yaml.
    """
    id: str = Field(description="Unique identifier for the test case")
    category: str = Field(description="Attack category or 'benign_control'")
    listing_text: str = Field(description="Free-text product listing or prompt injection payload")
    target_product_id: str = Field(description="Target catalog product ID")
    expected_outcome: str = Field(description="Expected Intent decision: 'BLOCK' or 'ALLOW'")
    expected_rule_codes: list[str] = Field(default_factory=list, description="Expected violation rule codes when blocked")
    merchant_domain: Optional[str] = Field(default=None, description="Optional override domain")
    quantity: int = Field(default=1, description="Quantity proposed or targeted")
    notes: Optional[str] = Field(default=None, description="Human description of attack mechanism")


class BenchmarkOutcome(BaseModel):
    """
    Outcome of evaluating a single test case through baseline and protected paths.
    """
    case_id: str
    category: str
    expected_outcome: str
    baseline_executed: bool
    protected_status: str
    protected_violations: list[str] = Field(default_factory=list)
    rule_latencies_ms: dict[str, float] = Field(default_factory=dict)
    total_latency_ms: float = 0.0
    agent_reasoning: str = ""
    agent_product_id: str = ""
    agent_domain: str = ""
    agent_quantity: int = 1


class BaselineDetail(BaseModel):
    """
    Specific baseline evaluation result (Forced Compromise or Real Model Naive Agent).
    """
    name: str
    description: str
    model_name: str
    date: str
    attack_success_rate: float
    successful_attacks: int
    total_attacks: int
    prompt: str


class NotCoveredCase(BaseModel):
    """
    Architectural boundary case not designed to be stopped by pre-purchase gateway.
    Explicitly disclosed as NOT_BLOCKED.
    """
    id: str
    name: str
    description: str
    why_not_blocked: str
    expected_status: str = "NOT_BLOCKED"
    boundary_layer: str


class SecondCategoryResult(BaseModel):
    """
    Verification metrics for a second product category with distinct attribute schema.
    Proves Rule 2 is generic across non-laptop attributes.
    """
    category_name: str
    attribute_schema: list[str]
    total_cases: int
    attack_cases: int
    benign_controls: int
    attacks_blocked: int
    controls_allowed: int
    protected_asr: float
    generic_rule_2_verified: bool = True
    cases: list[BenchmarkOutcome] = Field(default_factory=list)


class StabilityMetric(BaseModel):
    """
    Run-to-run stability across repeated executions.
    """
    stability_rate: float
    total_repeated_runs: int
    label: str


class BenchmarkRunResult(BaseModel):
    """
    Overall result of a benchmark execution run.
    """
    headline: str = "56 unique attacks and 16 benign controls"
    threat_model: str = "The agent is assumed compromised, so the benchmark measures the gateway, not the LLM."
    timestamp: str
    mode: str
    runs_per_case: int
    total_cases: int
    unique_attacks: int = 56
    unique_benign: int = 16
    baseline_attack_success_rate: float
    protected_attack_success_rate: float
    baseline_false_positive_rate: float
    protected_false_positive_rate: float
    baselines: dict[str, Any] = Field(default_factory=dict)
    stability: Optional[StabilityMetric] = None
    not_covered: list[NotCoveredCase] = Field(default_factory=list)
    second_category: Optional[SecondCategoryResult] = None
    failures: list[dict[str, Any]] = Field(default_factory=list)
    category_metrics: dict[str, dict[str, Any]] = Field(default_factory=dict)
    latency_ms_per_rule: dict[str, float] = Field(default_factory=dict)
    case_results: list[BenchmarkOutcome] = Field(default_factory=list)
