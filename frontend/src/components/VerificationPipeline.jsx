import React from 'react'
import {
  ShieldAlert,
  ShieldCheck,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  RotateCcw,
  ArrowRight,
  Terminal,
  Server,
  Lock,
} from 'lucide-react'

export default function VerificationPipeline({
  evaluation,
  agentRequest,
  policy,
  stepStates,
}) {
  const isBlocked = evaluation?.status === 'BLOCKED'
  const isVerified = evaluation?.status === 'VERIFIED_READY_FOR_PAYPAL' || evaluation?.status === 'CAPTURED'

  // Helper to determine status for each of the 4 rules
  const getRuleVerdict = (ruleNumber) => {
    if (!evaluation) return { status: 'idle', message: 'Awaiting submission' }
    
    // Check if evaluation is in progress (staggered animation)
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
        detail: `Merchant domain verified. Availability: InStock`,
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
        detail: `All ${Object.keys(policy?.required_structured_attributes || {}).length} required attributes match authoritative catalog.`,
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
        detail: `Qty ${agentRequest?.quantity || 1} <= ${policy?.max_quantity || 1}. Subtotal $${evaluation.computed_subtotal || '0.00'} within $${policy?.max_order_total || '1,200.00'} budget.`,
      }
    }

    if (ruleNumber === 4) {
      if (violations.length > 0) {
        return {
          status: 'blocked',
          detail: 'Payment construction aborted. Zero funds routed to PayPal.',
        }
      }
      return {
        status: 'passed',
        detail: evaluation.paypal_order_id
          ? `PayPal Sandbox order created: ${evaluation.paypal_order_id}`
          : 'Verified safe. Ready for PayPal order construction.',
      }
    }

    return { status: 'idle', message: '' }
  }

  const rulesMeta = [
    {
      num: 1,
      name: 'Rule 1: Offer Domain & Availability',
      desc: 'Verify retailer domain exists in product offers and stock status matches policy.',
    },
    {
      num: 2,
      name: 'Rule 2: Structured Attribute Verification',
      desc: 'Fail-closed verification: requires exact matches on canonical Channel3 handles (e.g. ram, storage).',
    },
    {
      num: 3,
      name: 'Rule 3: Quantity & Arithmetic Enforcement',
      desc: 'Ensures quantity is within policy cap and subtotal (unit_price * qty) does not exceed budget limit.',
    },
    {
      num: 4,
      name: 'Rule 4: PayPal Safe Payload Routing',
      desc: 'Only constructs payment request if Rules 1–3 pass with zero violations.',
    },
  ]

  return (
    <div className="verification-pipeline-container">
      {/* Untrusted Agent Output Panel */}
      <div className="agent-submission-box">
        <div className="submission-header">
          <Terminal size={15} />
          <span className="submission-title">Untrusted AI Shopping Agent Output</span>
          <span className="isolation-pill font-mono">ISOLATED TRUST BOUNDARY</span>
        </div>

        <div className="submission-body">
          <div className="reasoning-row">
            <span className="reasoning-label font-mono">LLM Reasoning:</span>
            <p className="reasoning-text">
              {agentRequest?.agent_reasoning || 'No agent run yet. Select a preset or test order to begin.'}
            </p>
          </div>

          <div className="payload-row">
            <span className="payload-label font-mono">Submitted Intent:</span>
            <code className="payload-json font-mono">
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
                : '{ ... }'}
            </code>
          </div>
        </div>
      </div>

      {/* Signature Moment: 4 Sequential Rules */}
      <div className="pipeline-rules-section">
        <div className="pipeline-header">
          <Lock size={16} />
          <h3>Deterministic Verification Pipeline (Pure-Code Gate)</h3>
        </div>

        <div className="rules-stack">
          {rulesMeta.map((rule) => {
            const verdict = getRuleVerdict(rule.num)
            return (
              <div
                key={rule.num}
                className={`rule-card ${verdict.status}`}
              >
                <div className="rule-card-left">
                  <div className="rule-status-icon">
                    {verdict.status === 'passed' && (
                      <CheckCircle2 size={18} className="text-success" />
                    )}
                    {verdict.status === 'failed' && (
                      <XCircle size={18} className="text-danger" />
                    )}
                    {verdict.status === 'blocked' && (
                      <AlertTriangle size={18} className="text-muted" />
                    )}
                    {verdict.status === 'checking' && (
                      <span className="spinner-indicator"></span>
                    )}
                    {verdict.status === 'idle' && (
                      <span className="idle-indicator font-mono">{rule.num}</span>
                    )}
                  </div>

                  <div className="rule-info">
                    <h4 className="rule-name">{rule.name}</h4>
                    <p className="rule-desc">{rule.desc}</p>
                    {verdict.detail && (
                      <div className="rule-detail font-mono">
                        {verdict.detail}
                      </div>
                    )}
                  </div>
                </div>

                <div className="rule-card-right">
                  <span className={`verdict-chip font-mono ${verdict.status}`}>
                    {verdict.status.toUpperCase()}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Gateway Verdict Banner */}
      {evaluation && (
        <div className={`verdict-banner ${isBlocked ? 'blocked' : 'verified'}`}>
          <div className="verdict-banner-left">
            {isBlocked ? (
              <ShieldAlert size={28} className="banner-icon danger" />
            ) : (
              <ShieldCheck size={28} className="banner-icon success" />
            )}
            <div>
              <div className="verdict-status-title">
                <span>GATEWAY VERDICT:</span>
                <span className="status-name font-mono">{evaluation.status}</span>
              </div>
              <p className="verdict-sub">
                Attempt ID: <span className="font-mono">{evaluation.attempt_id}</span>
                {evaluation.computed_subtotal && (
                  <> · Subtotal: <span className="font-mono">${evaluation.computed_subtotal}</span></>
                )}
              </p>
            </div>
          </div>

          {evaluation.remediation && (
            <div className="remediation-pill">
              <span className="remediation-action font-mono">
                ACTION: {evaluation.remediation.action}
              </span>
              <p className="remediation-instruction font-mono">
                {evaluation.remediation.instruction}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
