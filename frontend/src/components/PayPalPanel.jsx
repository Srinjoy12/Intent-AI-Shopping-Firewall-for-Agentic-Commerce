import React, { useState, useEffect } from 'react'
import { Copy, Check, CheckCircle2, Clock } from 'lucide-react'

export default function PayPalPanel({
  evaluation,
  _onCaptureOrder,
  onRefundCapture,
  _isCapturing,
  onApprovalSuccess,
}) {
  const [refundStatus, setRefundStatus] = useState(null)
  const [isRefunding, setIsRefunding] = useState(false)
  const [isProcessingApproval, setIsProcessingApproval] = useState(false)
  const [approvalActionDone, setApprovalActionDone] = useState(null)
  const [approvalError, setApprovalError] = useState(null)
  const [secondsRemaining, setSecondsRemaining] = useState(900)
  const [copiedField, setCopiedField] = useState(null)

  useEffect(() => {
    if (evaluation?.needs_human_approval) {
      setSecondsRemaining(900)
      setApprovalActionDone(null)
      setApprovalError(null)
    }
  }, [evaluation?.approval_id, evaluation?.needs_human_approval])

  useEffect(() => {
    if (!evaluation?.needs_human_approval || approvalActionDone || secondsRemaining <= 0) {
      return
    }
    const timer = setInterval(() => {
      setSecondsRemaining((prev) => {
        if (prev <= 1) {
          clearInterval(timer)
          return 0
        }
        return prev - 1
      })
    }, 1000)
    return () => clearInterval(timer)
  }, [evaluation?.needs_human_approval, approvalActionDone, secondsRemaining])

  const formatCountdown = (secs) => {
    const mins = Math.floor(secs / 60)
    const remSecs = secs % 60
    return `${mins.toString().padStart(2, '0')}:${remSecs.toString().padStart(2, '0')}`
  }

  const isRefunded = evaluation?.status === 'REFUNDED' || !!refundStatus
  const isBlocked = evaluation?.status === 'BLOCKED' || approvalActionDone?.status === 'DENIED'
  const needsApproval = evaluation?.needs_human_approval && !approvalActionDone
  const isIdle = !evaluation

  const copyToClipboard = (text, fieldName) => {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text)
      setCopiedField(fieldName)
      setTimeout(() => setCopiedField(null), 2000)
    }
  }

  const handleRefund = async () => {
    const captureId = evaluation?.paypal_capture_id || approvalActionDone?.capture_id
    if (!captureId || isRefunding || isRefunded) return
    setIsRefunding(true)
    try {
      const res = await onRefundCapture(captureId)
      setRefundStatus(res)
    } catch (err) {
      console.error('Refund failed:', err)
    } finally {
      setIsRefunding(false)
    }
  }

  const handleApprovalAction = async (action) => {
    if ((!evaluation?.approval_id && !evaluation?.approval_token) || isProcessingApproval) return
    setIsProcessingApproval(true)
    setApprovalError(null)
    try {
      let res
      if (evaluation?.approval_id) {
        res = await fetch(`/api/demo/approvals/${evaluation.approval_id}/resolve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: action.toLowerCase() }),
        })
      } else {
        res = await fetch('/api/approvals/action', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            token: evaluation.approval_token,
            action: action,
          }),
        })
      }
      const data = await res.json()
      if (res.ok && (data.status === 'APPROVED' || data.status === 'DENIED')) {
        setApprovalActionDone(data)
        if (onApprovalSuccess) {
          onApprovalSuccess(data)
        }
      } else {
        setApprovalError(data.detail || data.message || 'Approval action failed')
      }
    } catch (err) {
      console.error('Error handling approval action:', err)
      setApprovalError('Failed to dispatch approval resolution')
    } finally {
      setIsProcessingApproval(false)
    }
  }

  const orderId = evaluation?.paypal_order_id || approvalActionDone?.paypal_order_id || '64J40959H0815504S'
  const captureId = evaluation?.paypal_capture_id || approvalActionDone?.capture_id || '55758229E8519101W'
  const amountStr = evaluation?.computed_subtotal ? `$${Number(evaluation.computed_subtotal).toFixed(2)} USD` : '$749.99 USD'

  return (
    <div className="panel settlement-panel paypal-box">
      <div className="panel-header">
        <h2 className="panel-title">Settlement</h2>
      </div>

      <div className="settlement-body">
        {/* State 1: IDLE */}
        {isIdle && (
          <p className="settlement-idle-message">
            No payment created yet. Run a scenario to see the PayPal sandbox result.
          </p>
        )}

        {/* State 2: BLOCKED */}
        {!isIdle && isBlocked && (
          <div className="settlement-kv-grid">
            <div className="kv-row">
              <span className="kv-key">Authorized amount</span>
              <span className="kv-val font-mono tabular-nums">$0.00</span>
            </div>
            <div className="kv-row">
              <span className="kv-key">PayPal calls</span>
              <span className="kv-val font-mono tabular-nums">0 (dispatches blocked)</span>
            </div>
            <div className="kv-row">
              <span className="kv-key">Reason code</span>
              <span className="kv-val font-mono status-text-danger">
                {evaluation?.violations?.[0]?.rule || 'STRUCTURED_ATTRIBUTE_MISMATCH'}
              </span>
            </div>
            <div className="kv-row">
              <span className="kv-key">Remediation action</span>
              <span className="kv-val">
                {evaluation?.remediation?.action ||
                  evaluation?.violations?.[0]?.detail ||
                  'Select SKU matching 16GB RAM policy requirement'}
              </span>
            </div>
          </div>
        )}

        {/* State 3: PENDING HUMAN APPROVAL (Outcome B) */}
        {!isIdle && needsApproval && (
          <div className="settlement-approval-view">
            <div className="settlement-kv-grid">
              <div className="kv-row">
                <span className="kv-key">Order ID</span>
                <span className="kv-val font-mono">{orderId}</span>
              </div>
              <div className="kv-row">
                <span className="kv-key">Threshold trigger</span>
                <span className="kv-val">
                  {amountStr} exceeds $1,000.00 auto-approve limit
                </span>
              </div>
              <div className="kv-row">
                <span className="kv-key">Status</span>
                <span className="status-tag status-tag-warning">
                  <Clock size={13} aria-hidden="true" />
                  <span>Pending approval</span>
                </span>
              </div>
              <div className="kv-row">
                <span className="kv-key">Expires in</span>
                <span className="kv-val font-mono tabular-nums">
                  {formatCountdown(secondsRemaining)}
                </span>
              </div>
            </div>

            {approvalError && (
              <p className="approval-error-msg">{approvalError}</p>
            )}

            <div className="approval-action-buttons">
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => handleApprovalAction('APPROVE')}
                disabled={isProcessingApproval || secondsRemaining <= 0}
              >
                {isProcessingApproval ? 'Processing…' : 'Approve and release payment'}
              </button>
              <button
                type="button"
                className="btn btn-destructive-outline"
                onClick={() => handleApprovalAction('DENY')}
                disabled={isProcessingApproval || secondsRemaining <= 0}
              >
                Deny
              </button>
            </div>
          </div>
        )}

        {/* State 4: CAPTURED (Outcome A or Approved Outcome B) */}
        {!isIdle && !isBlocked && !needsApproval && (
          <div className="settlement-captured-view">
            <div className="settlement-kv-grid">
              <div className="kv-row">
                <span className="kv-key">Order ID</span>
                <div className="kv-val-with-copy">
                  <span className="font-mono">{orderId}</span>
                  <button
                    type="button"
                    className="btn-icon-copy"
                    onClick={() => copyToClipboard(orderId, 'order')}
                    title="Copy Order ID"
                  >
                    {copiedField === 'order' ? <Check size={13} color="var(--status-success)" /> : <Copy size={13} />}
                  </button>
                </div>
              </div>
              <div className="kv-row">
                <span className="kv-key">Capture ID</span>
                <div className="kv-val-with-copy">
                  <span className="font-mono">{captureId}</span>
                  <button
                    type="button"
                    className="btn-icon-copy"
                    onClick={() => copyToClipboard(captureId, 'capture')}
                    title="Copy Capture ID"
                  >
                    {copiedField === 'capture' ? <Check size={13} color="var(--status-success)" /> : <Copy size={13} />}
                  </button>
                </div>
              </div>
              <div className="kv-row">
                <span className="kv-key">Amount</span>
                <span className="kv-val font-mono tabular-nums">{amountStr}</span>
              </div>
              <div className="kv-row">
                <span className="kv-key">Status</span>
                <span className="status-tag status-tag-success">
                  <CheckCircle2 size={13} aria-hidden="true" />
                  <span>{isRefunded ? 'Refunded' : 'Captured'}</span>
                </span>
              </div>
            </div>

            {/* Refund Action */}
            <div className="settlement-actions-footer">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={handleRefund}
                disabled={isRefunding || isRefunded}
              >
                {isRefunding ? 'Refunding…' : isRefunded ? 'Refund settled' : 'Refund transaction'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
