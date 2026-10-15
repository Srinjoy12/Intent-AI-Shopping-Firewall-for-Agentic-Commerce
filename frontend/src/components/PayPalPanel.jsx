import React, { useState } from 'react'
import { CreditCard, CheckCircle2, RefreshCw, RotateCcw, ShieldCheck, ShieldAlert, Lock } from 'lucide-react'

export default function PayPalPanel({
  evaluation,
  onCaptureOrder,
  onRefundCapture,
  isCapturing,
}) {
  const [refundStatus, setRefundStatus] = useState(null)
  const [isRefunding, setIsRefunding] = useState(false)
  const [refundError, setRefundError] = useState(null)

  const isVerified = evaluation?.status === 'VERIFIED_READY_FOR_PAYPAL'
  const isCaptured = evaluation?.status === 'CAPTURED'
  const isRefunded = evaluation?.status === 'REFUNDED' || !!refundStatus
  const isBlocked = evaluation?.status === 'BLOCKED'

  const handleRefund = async () => {
    if (!evaluation?.paypal_capture_id || isRefunding || isRefunded) return
    setIsRefunding(true)
    setRefundError(null)
    try {
      const res = await onRefundCapture(evaluation.paypal_capture_id)
      setRefundStatus(res)
    } catch (err) {
      console.error('Refund failed:', err)
      setRefundError(err?.message || 'Refund request error')
    } finally {
      setIsRefunding(false)
    }
  }

  return (
    <div className="paypal-panel-container">
      <div className="paypal-panel-header">
        <div className="paypal-header-left">
          <div className="paypal-icon-box">
            <span className="paypal-p">P</span>
          </div>
          <div>
            <h3 className="paypal-title">PayPal Sandbox Settlement</h3>
            <span className="paypal-subtitle">Secure Merchant Gateway</span>
          </div>
        </div>
        <span className="paypal-env-pill">Sandbox Mode</span>
      </div>

      <div className="paypal-panel-body">
        {/* Blocked State */}
        {isBlocked && (
          <div className="settlement-state-card blocked">
            <div className="state-icon-row">
              <Lock size={18} className="text-danger" />
              <h4 className="state-heading">Transaction Intercepted &bull; $0 Charged</h4>
            </div>
            <p className="state-text">
              Deterministic firewall rules failed. Execution terminated at the trust boundary before constructing payment parameters. Zero funds were authorized or captured on PayPal Sandbox.
            </p>
          </div>
        )}

        {/* Ready for Human Approval (Outcome B) */}
        {isVerified && (
          <div className="settlement-state-card ready">
            <div className="outcome-notice-box">
              <ShieldCheck size={16} className="text-paypal-blue shrink-0" />
              <span>
                <strong>Outcome B Hold:</strong> Subtotal (${evaluation.computed_subtotal} USD) exceeds the $1,000 auto-capture threshold. Rules verified safe &bull; Pending 1-click human authorization.
              </span>
            </div>

            <div className="transaction-summary-grid">
              <div className="summary-item">
                <span className="summary-label">PayPal Order ID</span>
                <span className="summary-value font-mono highlight">
                  {evaluation.paypal_order_id || 'PENDING'}
                </span>
              </div>

              <div className="summary-item">
                <span className="summary-label">Verified Total</span>
                <span className="summary-value font-mono text-success">
                  ${evaluation.computed_subtotal} USD
                </span>
              </div>

              <div className="summary-item">
                <span className="summary-label">Gateway Status</span>
                <span className="summary-value status-badge ready">
                  Approved for Capture
                </span>
              </div>
            </div>

            <button
              id="btn-capture-paypal"
              type="button"
              className="btn-paypal-gold full-width"
              disabled={isCapturing || !evaluation.paypal_order_id}
              onClick={() => onCaptureOrder(evaluation.paypal_order_id)}
            >
              {isCapturing ? (
                <>
                  <RefreshCw size={15} className="spin-icon" />
                  <span>Capturing Sandbox Funds...</span>
                </>
              ) : (
                <>
                  <CheckCircle2 size={16} />
                  <span>Approve &amp; Capture ${evaluation.computed_subtotal} on PayPal</span>
                </>
              )}
            </button>
          </div>
        )}

        {/* Captured State */}
        {isCaptured && !isRefunded && (
          <div className="settlement-state-card captured">
            <div className="state-icon-row">
              <CheckCircle2 size={18} className="text-success" />
              <h4 className="state-heading text-success">Payment Captured Successfully</h4>
            </div>

            <div className="transaction-summary-grid">
              <div className="summary-item">
                <span className="summary-label">PayPal Order ID</span>
                <span className="summary-value font-mono">
                  {evaluation.paypal_order_id}
                </span>
              </div>

              <div className="summary-item">
                <span className="summary-label">Capture ID</span>
                <span className="summary-value font-mono text-success">
                  {evaluation.paypal_capture_id || 'CAP_SANDBOX_SUCCESS'}
                </span>
              </div>

              <div className="summary-item">
                <span className="summary-label">Settlement</span>
                <span className="summary-value status-badge success">
                  Completed
                </span>
              </div>
            </div>

            <div className="refund-bar">
              <button
                id="btn-refund-paypal"
                type="button"
                className="btn-refund-action"
                disabled={isRefunding || isRefunded}
                onClick={handleRefund}
              >
                {isRefunding ? (
                  <>
                    <RefreshCw size={13} className="spin-icon" />
                    <span>Processing Refund...</span>
                  </>
                ) : (
                  <>
                    <RotateCcw size={13} />
                    <span>Issue 100% Sandbox Refund</span>
                  </>
                )}
              </button>

              <span className="refund-guarantee">
                Safe test mode &bull; Fully reversible with 1 click
              </span>
            </div>

            {refundError && (
              <span className="refund-error-msg">
                ✕ {refundError}
              </span>
            )}
          </div>
        )}

        {/* Refunded State */}
        {isRefunded && (
          <div className="settlement-state-card refunded">
            <div className="state-icon-row">
              <RotateCcw size={18} className="text-purple-600" />
              <h4 className="state-heading text-purple-900">Payment 100% Refunded on Sandbox</h4>
            </div>

            <div className="transaction-summary-grid">
              <div className="summary-item">
                <span className="summary-label">Capture Ref</span>
                <span className="summary-value font-mono">
                  {evaluation?.paypal_capture_id || refundStatus?.capture_id}
                </span>
              </div>

              <div className="summary-item">
                <span className="summary-label">Status</span>
                <span className="summary-value status-badge refunded">
                  Refunded
                </span>
              </div>
            </div>

            <p className="refund-confirmation">
              ✓ Funds returned to Sandbox account. Zero net balance change.
            </p>
          </div>
        )}

        {/* Idle State */}
        {!evaluation && (
          <div className="settlement-idle-box">
            <p className="idle-prompt">
              Select an attack scenario or verified purchase to view live PayPal Sandbox payment processing.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
