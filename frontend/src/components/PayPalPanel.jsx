import React, { useState } from 'react'
import { CreditCard, CheckCircle, RefreshCw, RotateCcw, Lock, ShieldCheck, AlertCircle } from 'lucide-react'

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
          <CreditCard size={18} className="paypal-logo-icon" />
          <h3 className="paypal-title">PayPal Sandbox Payment Settlement</h3>
        </div>
        <span className="paypal-env-tag font-mono">SANDBOX GATEWAY</span>
      </div>

      <div className="paypal-panel-body">
        {isBlocked && (
          <div className="paypal-state-blocked">
            <Lock size={20} className="text-danger" />
            <div className="state-text">
              <h4 className="state-title">Payment Intercepted & Halted</h4>
              <p className="state-desc">
                Because deterministic rules failed, the gateway terminated before contacting PayPal.
                No credit card charges or PayPal authorizations were attempted. Zero risk of account drain.
              </p>
            </div>
          </div>
        )}

        {isVerified && (
          <div className="paypal-state-ready">
            <div className="flex items-center gap-2 mb-2 p-2 bg-sky-950/60 border border-sky-800/80 rounded text-sky-300 text-xs font-mono">
              <ShieldCheck size={16} className="text-sky-400 shrink-0" />
              <span>Outcome B: Subtotal &gt; $1,000.00 auto-approve threshold. Cleared by Gateway &bull; Pending 1-click human approval.</span>
            </div>

            <div className="order-details-grid">
              <div className="detail-item">
                <span className="detail-label font-mono">PAYPAL ORDER ID:</span>
                <span className="detail-val font-mono highlight">
                  {evaluation.paypal_order_id || 'PENDING_INIT'}
                </span>
              </div>

              <div className="detail-item">
                <span className="detail-label font-mono">VERIFIED AMOUNT:</span>
                <span className="detail-val font-mono text-emerald-400 font-bold">
                  ${evaluation.computed_subtotal} USD
                </span>
              </div>

              <div className="detail-item">
                <span className="detail-label font-mono">PAYPAL STATUS:</span>
                <span className="detail-val font-mono status-ready">
                  APPROVED_FOR_CAPTURE
                </span>
              </div>
            </div>

            <p className="pricing-note font-mono">{evaluation.pricing_note}</p>

            <button
              id="btn-capture-paypal"
              type="button"
              className="btn-capture-paypal"
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
                  <CheckCircle size={15} />
                  <span>Approve & Capture Order on Sandbox (${evaluation.computed_subtotal} USD)</span>
                </>
              )}
            </button>
          </div>
        )}

        {isCaptured && !isRefunded && (
          <div className="paypal-state-captured">
            <div className="captured-header">
              <CheckCircle size={20} className="text-success" />
              <h4>Payment Captured Successfully</h4>
            </div>

            <div className="captured-details">
              <div className="detail-item">
                <span className="detail-label font-mono">CAPTURE ID:</span>
                <span className="detail-val font-mono">
                  {evaluation.paypal_capture_id || 'CAP_SANDBOX_SUCCESS'}
                </span>
              </div>
              <div className="detail-item">
                <span className="detail-label font-mono">SETTLEMENT:</span>
                <span className="detail-val font-mono text-emerald-400">COMPLETED</span>
              </div>
            </div>

            <div className="refund-action-wrap">
              <button
                id="btn-refund-paypal"
                type="button"
                className="btn-refund-paypal"
                disabled={isRefunding || isRefunded}
                onClick={handleRefund}
              >
                {isRefunding ? (
                  <>
                    <RefreshCw size={14} className="spin-icon" />
                    <span>Processing Sandbox Refund...</span>
                  </>
                ) : (
                  <>
                    <RotateCcw size={14} />
                    <span>Issue Full Refund on Sandbox</span>
                  </>
                )}
              </button>

              {refundError && (
                <span className="text-xs text-rose-400 font-mono">
                  ✕ {refundError}
                </span>
              )}
            </div>
          </div>
        )}

        {isRefunded && (
          <div className="paypal-state-captured border-purple-800/80 bg-purple-950/20">
            <div className="captured-header">
              <RotateCcw size={20} className="text-purple-400" />
              <h4 className="text-purple-300">Payment 100% Refunded on Sandbox</h4>
            </div>

            <div className="captured-details">
              <div className="detail-item">
                <span className="detail-label font-mono">ORIGINAL CAPTURE:</span>
                <span className="detail-val font-mono">
                  {evaluation?.paypal_capture_id || refundStatus?.capture_id}
                </span>
              </div>
              <div className="detail-item">
                <span className="detail-label font-mono">STATUS:</span>
                <span className="detail-val font-mono text-purple-300 font-bold">REFUNDED</span>
              </div>
            </div>

            <div className="refund-action-wrap">
              <span className="refund-success-note font-mono text-purple-300">
                ✓ Full refund confirmed on PayPal Sandbox. 100% reversible demo.
              </span>
            </div>
          </div>
        )}

        {!evaluation && (
          <div className="paypal-state-idle">
            <p className="idle-text">
              Run an attack preset, legitimate order, or autonomous self-healing loop to test PayPal Sandbox settlement.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
