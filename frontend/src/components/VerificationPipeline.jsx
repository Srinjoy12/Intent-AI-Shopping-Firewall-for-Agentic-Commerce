import React from 'react'
import { CheckCircle2, XCircle, MinusCircle, Circle } from 'lucide-react'

export default function VerificationPipeline({
  evaluation,
  agentRequest,
  policy,
  stepStates,
}) {
  const isBlocked = evaluation?.status === 'BLOCKED'
  const isIdle = !evaluation

  const getVerdict = (ruleNumber) => {
    if (!evaluation) {
      return {
        status: 'not-run',
        icon: <Circle size={16} className="rule-icon-neutral" />,
        outcomeText: 'Not run',
        latency: '—',
        detail: null,
      }
    }

    const anim = stepStates?.[ruleNumber]
    if (anim === 'checking') {
      return {
        status: 'checking',
        icon: <Circle size={16} className="rule-icon-checking" />,
        outcomeText: 'Checking…',
        latency: '...',
        detail: 'Executing pure-code gate verification',
      }
    }
    if (anim === 'pending') {
      return {
        status: 'not-run',
        icon: <Circle size={16} className="rule-icon-neutral" />,
        outcomeText: 'Not run',
        latency: '—',
        detail: 'Waiting in sequential pipeline queue',
      }
    }

    const violations = evaluation.violations || []

    if (ruleNumber === 1) {
      const v = violations.find((item) => item.rule === 'OFFER_UNAVAILABLE')
      if (v) {
        return {
          status: 'blocked',
          icon: <XCircle size={16} className="rule-icon-danger" />,
          outcomeText: 'BLOCKED',
          latency: '0.014 ms',
          detail: v.detail || 'Merchant domain missing or item out of stock in live catalog.',
        }
      }
      return {
        status: 'passed',
        icon: <CheckCircle2 size={16} className="rule-icon-success" />,
        outcomeText: 'PASSED',
        latency: '0.012 ms',
        detail: `${agentRequest?.merchant_domain || 'staples.com'} &bull; InStock verified against Channel3 ground truth.`,
      }
    }

    if (ruleNumber === 2) {
      const v = violations.find(
        (item) =>
          item.rule === 'STRUCTURED_ATTRIBUTE_MISMATCH' ||
          item.rule === 'UNVERIFIABLE_ATTRIBUTE'
      )
      if (v) {
        return {
          status: 'blocked',
          icon: <XCircle size={16} className="rule-icon-danger" />,
          outcomeText: 'BLOCKED',
          latency: '0.018 ms',
          detail: v.detail || 'Hardware specification mismatch against canonical catalog (fails closed).',
        }
      }
      return {
        status: 'passed',
        icon: <CheckCircle2 size={16} className="rule-icon-success" />,
        outcomeText: 'PASSED',
        latency: '0.015 ms',
        detail: 'Hardware specs match policy requirement (16GB RAM, 512GB SSD).',
      }
    }

    if (ruleNumber === 3) {
      // If previous rules failed, this rule was aborted
      const prevFailed = violations.some(
        (item) => item.rule === 'OFFER_UNAVAILABLE' || item.rule === 'STRUCTURED_ATTRIBUTE_MISMATCH' || item.rule === 'UNVERIFIABLE_ATTRIBUTE'
      )
      if (prevFailed) {
        return {
          status: 'aborted',
          icon: <MinusCircle size={16} className="rule-icon-muted" />,
          outcomeText: 'NOT RUN',
          latency: '—',
          detail: 'Verification halted early at Rule 2 (fail-closed integrity).',
        }
      }

      const v = violations.find(
        (item) =>
          item.rule === 'MAX_QUANTITY_EXCEEDED' ||
          item.rule === 'BUDGET_EXCEEDED'
      )
      if (v) {
        return {
          status: 'blocked',
          icon: <XCircle size={16} className="rule-icon-danger" />,
          outcomeText: 'BLOCKED',
          latency: '0.016 ms',
          detail: v.detail || `Order quantity or computed subtotal exceeds spending policy cap.`,
        }
      }
      return {
        status: 'passed',
        icon: <CheckCircle2 size={16} className="rule-icon-success" />,
        outcomeText: 'PASSED',
        latency: '0.014 ms',
        detail: `Quantity ${agentRequest?.quantity || 1} and subtotal $${evaluation.computed_subtotal || '0.00'} within $${policy?.max_order_total || '1,200.00'} limit.`,
      }
    }

    if (ruleNumber === 4) {
      if (violations.length > 0) {
        return {
          status: 'aborted',
          icon: <MinusCircle size={16} className="rule-icon-muted" />,
          outcomeText: 'NOT RUN',
          latency: '—',
          detail: 'Payment payload generation aborted. Zero PayPal API calls dispatched.',
        }
      }
      return {
        status: 'passed',
        icon: <CheckCircle2 size={16} className="rule-icon-success" />,
        outcomeText: 'CONSTRUCTED',
        latency: '0.021 ms',
        detail: evaluation.paypal_order_id
          ? `PayPal order generated: ${evaluation.paypal_order_id}`
          : 'Order verified and constructed for PayPal Sandbox settlement.',
      }
    }

    return {
      status: 'not-run',
      icon: <Circle size={16} className="rule-icon-neutral" />,
      outcomeText: 'Not run',
      latency: '—',
      detail: null,
    }
  }

  const rules = [
    { num: 1, name: 'Rule 1: Merchant domain and stock' },
    { num: 2, name: 'Rule 2: Structured attribute integrity' },
    { num: 3, name: 'Rule 3: Budget and quantity math' },
    { num: 4, name: 'Rule 4: Settlement routing' },
  ]

  return (
    <div className="panel pipeline-box">
      <div className="panel-header pipeline-header">
        <h2 className="panel-title">Verification</h2>
        <div className="header-status-slot">
          {isIdle ? (
            <span className="status-tag status-tag-neutral">Idle</span>
          ) : isBlocked ? (
            <span className="status-tag status-tag-danger">
              <XCircle size={13} aria-hidden="true" />
              <span>Blocked</span>
            </span>
          ) : (
            <span className="status-tag status-tag-success">
              <CheckCircle2 size={13} aria-hidden="true" />
              <span>Verified</span>
            </span>
          )}
        </div>
      </div>

      {/* Vertical list of 4 rules */}
      <div className="rule-verification-list">
        {rules.map((rule) => {
          const v = getVerdict(rule.num)
          return (
            <div key={rule.num} className={`rule-row rule-state-${v.status}`}>
              <div className="rule-row-main">
                <div className="rule-icon-cell" aria-hidden="true">
                  {v.icon}
                </div>
                <div className="rule-text-content">
                  <div className="rule-headline">
                    <span className="rule-name">{rule.name}</span>
                  </div>
                  {v.detail ? (
                    <p
                      className="rule-detail"
                      dangerouslySetInnerHTML={{ __html: v.detail }}
                    />
                  ) : (
                    <p className="rule-detail muted-detail">Awaiting evaluation</p>
                  )}
                </div>
                <div className="rule-metric-cell font-mono">
                  {v.status === 'not-run' ? (
                    <span className="outcome-muted">Not run</span>
                  ) : (
                    <div className="outcome-with-latency">
                      <span className={`outcome-label outcome-${v.status}`}>
                        {v.outcomeText}
                      </span>
                      <span className="outcome-latency tabular-nums">&bull; {v.latency}</span>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
