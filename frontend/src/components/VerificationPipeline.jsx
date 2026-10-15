import React, { useState } from 'react'
import {
  ShieldCheck,
  ShieldAlert,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Terminal,
  Lock,
} from 'lucide-react'

export default function VerificationPipeline({
  evaluation,
  agentRequest,
  policy,
  stepStates,
}) {
  const [showRawAgent, setShowRawAgent] = useState(false)
  const isBlocked = evaluation?.status === 'BLOCKED'
  const isVerified = evaluation?.status === 'VERIFIED_READY_FOR_PAYPAL' || evaluation?.status === 'CAPTURED'

  // Helper to determine status for each of the 4 rules
  const getRuleVerdict = (ruleNumber) => {
    if (!evaluation) return { status: 'idle', message: 'Awaiting evaluation' }

    const animState = stepStates?.[ruleNumber]
    if (animState === 'checking') {
      return { status: 'checking', message: 'Evaluating server-side constraints...' }
    }
    if (animState === 'pending') {
      return { status: 'idle', message: 'Queued' }
    }

    const violations = evaluation.violations || []

    if (ruleNumber === 1) {
      const v = violations.find((item) => item.rule === 'OFFER_UNAVAILABLE')
      if (v) return { status: 'failed', detail: v.detail }
      return {
        status: 'passed',
        detail: 'Merchant domain verified as authentic. Stock status: InStock.',
      }
    }

    if (ruleNumber === 2) {
      const v = violations.find(
        (item) =>
          item.rule === 'STRUCTURED_ATTRIBUTE_MISMATCH' ||
          item.rule === 'UNVERIFIABLE_ATTRIBUTE'
      )
      if (v) return { status: 'failed', detail: v.detail }
      return {
        status: 'passed',
        detail: `All required attributes (16GB RAM, 512GB Storage) match authoritative catalog.`,
      }
    }

    if (ruleNumber === 3) {
      const v = violations.find(
        (item) =>
          item.rule === 'MAX_QUANTITY_EXCEEDED' ||
          item.rule === 'BUDGET_EXCEEDED'
      )
      if (v) return { status: 'failed', detail: v.detail }
      return {
        status: 'passed',
        detail: `Quantity (${agentRequest?.quantity || 1}) within limit. Subtotal $${evaluation.computed_subtotal || '0.00'} within $${policy?.max_order_total || '1,200.00'} budget.`,
      }
    }

    if (ruleNumber === 4) {
      if (violations.length > 0) {
        return {
          status: 'blocked',
          detail: 'Payment construction aborted. 0 funds routed to PayPal.',
        }
      }
      return {
        status: 'passed',
        detail: evaluation.paypal_order_id
          ? `PayPal Sandbox order constructed: ${evaluation.paypal_order_id}`
          : 'Verified compliant. Safe to route to PayPal Sandbox.',
      }
    }

    return { status: 'idle', message: '' }
  }

  const rulesMeta = [
    {
      num: 1,
      name: 'Rule 1: Domain & Stock Verification',
      desc: 'Validates retailer domain exists in official feeds and item is in stock.',
    },
    {
      num: 2,
      name: 'Rule 2: Structured Attribute Match',
      desc: 'Deterministic check against canonical Channel3 handles (16GB RAM, 512GB SSD).',
    },
    {
      num: 3,
      name: 'Rule 3: Quantity & Arithmetic Cap',
      desc: 'Enforces maximum quantity (1 unit) and total order budget ($1,200.00).',
    },
    {
      num: 4,
      name: 'Rule 4: Safe Payment Construction',
      desc: 'Constructs PayPal Sandbox order only if Rules 1–3 pass with zero violations.',
    },
  ]

  return (
    <div className="verification-pipeline-container">
      {/* Pipeline Header */}
      <div className="pipeline-header">
        <div className="pipeline-title-group">
          <Lock size={16} className="text-paypal-blue" />
          <h3 className="pipeline-title">Deterministic Firewall Pipeline</h3>
        </div>
        <span className="pipeline-badge">Pure-Code Engine</span>
      </div>

      {/* 4 Sequential Deterministic Rules */}
      <div className="rules-stack">
        {rulesMeta.map((rule) => {
          const verdict = getRuleVerdict(rule.num)
          return (
            <div
              key={rule.num}
              className={`rule-card ${verdict.status}`}
            >
              <div className="rule-card-left">
                <div className={`rule-status-circle ${verdict.status}`}>
                  {verdict.status === 'passed' && (
                    <CheckCircle2 size={16} className="text-success" />
                  )}
                  {verdict.status === 'failed' && (
                    <XCircle size={16} className="text-danger" />
                  )}
                  {verdict.status === 'blocked' && (
                    <AlertTriangle size={16} className="text-muted" />
                  )}
                  {verdict.status === 'checking' && (
                    <span className="spinner-indicator"></span>
                  )}
                  {verdict.status === 'idle' && (
                    <span className="idle-step-num">{rule.num}</span>
                  )}
                </div>

                <div className="rule-info">
                  <div className="rule-header-line">
                    <h4 className="rule-name">{rule.name}</h4>
                    <span className={`verdict-pill ${verdict.status}`}>
                      {verdict.status === 'checking' ? 'Evaluating' : verdict.status.toUpperCase()}
                    </span>
                  </div>
                  <p className="rule-desc">{rule.desc}</p>
                  {verdict.detail && (
                    <div className={`rule-detail-message ${verdict.status}`}>
                      {verdict.detail}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* Gateway Verdict Banner */}
      {evaluation && (
        <div className={`verdict-card ${isBlocked ? 'blocked' : 'verified'}`}>
          <div className="verdict-card-header">
            {isBlocked ? (
              <ShieldAlert size={22} className="text-danger" />
            ) : (
              <ShieldCheck size={22} className="text-success" />
            )}
            <div>
              <div className="verdict-title-row">
                <span className="verdict-label">Gateway Decision:</span>
                <span className={`verdict-status-tag ${isBlocked ? 'blocked' : 'verified'}`}>
                  {evaluation.status === 'VERIFIED_READY_FOR_PAYPAL'
                    ? 'VERIFIED · READY FOR PAYPAL'
                    : evaluation.status === 'BLOCKED'
                    ? 'BLOCKED · RISK INTERCEPTED'
                    : evaluation.status}
                </span>
              </div>
              <p className="verdict-summary">
                {isBlocked
                  ? 'Payment intercepted before funds moved. Zero financial risk.'
                  : `Order cleared all 4 deterministic rules. Ready for settlement.`}
              </p>
            </div>
          </div>

          {evaluation.remediation && (
            <div className="remediation-box">
              <span className="remediation-tag">Self-Healing Guidance:</span>
              <p className="remediation-text">
                {evaluation.remediation.instruction}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Collapsible Agent Intent Drawer (Clean, non-intrusive) */}
      <div className="agent-intent-accordion">
        <button
          type="button"
          className="intent-toggle-btn"
          onClick={() => setShowRawAgent(!showRawAgent)}
        >
          <div className="flex items-center gap-2">
            <Terminal size={13} className="text-secondary" />
            <span>Untrusted AI Agent Intent &amp; Reasoning</span>
          </div>
          {showRawAgent ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>

        {showRawAgent && (
          <div className="intent-drawer-content">
            <div className="intent-block">
              <span className="intent-block-label">Agent Reasoning:</span>
              <p className="intent-reasoning-text">
                {agentRequest?.agent_reasoning || 'No agent activity recorded yet.'}
              </p>
            </div>

            <div className="intent-block">
              <span className="intent-block-label">Submitted Payload:</span>
              <pre className="intent-json-code">
                {agentRequest
                  ? JSON.stringify(
                      {
                        policy_id: agentRequest.policy_id,
                        product_id: agentRequest.product_id,
                        merchant_domain: agentRequest.merchant_domain,
                        quantity: agentRequest.quantity,
                      },
                      null,
                      2
                    )
                  : '// Awaiting agent submission'}
              </pre>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
