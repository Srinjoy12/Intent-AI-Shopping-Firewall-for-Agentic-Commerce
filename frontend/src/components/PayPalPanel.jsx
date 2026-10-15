import React, { useState } from 'react'
import { CreditCard, CheckCircle, RefreshCw, RotateCcw, Lock, ExternalLink } from 'lucide-react'

export default function PayPalPanel({
  evaluation,
  onCaptureOrder,
  onRefundCapture,
  isCapturing,
}) {
  const [refundStatus, setRefundStatus] = useState(null)
  const [isRefunding, setIsRefunding] = useState(false)

  const isVerified = evaluation?.status === 'VERIFIED_READY_FOR_PAYPAL'
  const isCaptured = evaluation?.status === 'CAPTURED'
  const isBlocked = evaluation?.status === 'BLOCKED'

  const handleRefund = async () => {
    if (!evaluation?.paypal_capture_id) return
    setIsRefunding(true)
    try {
      const res = await onRefundCapture(evaluation.paypal_capture_id)
      setRefundStatus(res)
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
                No credit card charges or PayPal authorizations were attempted.
              </p>
            </div>
          </div>
        )}

        {isVerified && (
          <div className="paypal-state-ready">
            <div className="order-details-grid">
              <div className="detail-item">
                <span className="detail-label font-mono">PAYPAL ORDER ID:</span>
                <span className="detail-val font-mono highlight">
                  {evaluation.paypal_order_id || 'PENDING_INIT'}
                </span>
              </div>

              <div className="detail-item">
                <span className="detail-label font-mono">VERIFIED AMOUNT:</span>
                <span className="detail-val font-mono">
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
                  <span>Capture Payment on PayPal</span>
                </>
              )}
            </button>
          </div>
        )}

        {isCaptured && (
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
                <span className="detail-val font-mono">COMPLETED</span>
              </div>
            </div>

            <div className="refund-action-wrap">
              <button
                id="btn-refund-paypal"
                type="button"
                className="btn-refund-paypal"
                disabled={isRefunding || refundStatus}
                onClick={handleRefund}
              >
                {isRefunding ? (
                  <>
                    <RefreshCw size={14} className="spin-icon" />
                    <span>Processing Refund...</span>
                  </>
                ) : (
                  <>
                    <RotateCcw size={14} />
                    <span>{refundStatus ? 'Payment Refunded' : 'Issue Full Refund on Sandbox'}</span>
                  </>
                )}
              </button>

              {refundStatus && (
                <span className="refund-success-note font-mono">
                  ✓ Refund Status: {refundStatus.status}
                </span>
              )}
            </div>
          </div>
        )}

        {!evaluation && (
          <div className="paypal-state-idle">
            <p className="idle-text">
              Run an attack preset or legitimate order to test PayPal Sandbox settlement.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
