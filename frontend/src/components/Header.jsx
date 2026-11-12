import React, { useState, useEffect } from 'react'
import { Copy, Check, X, AlertTriangle, AlertCircle } from 'lucide-react'

export default function Header({ policy, mandate, onNewMandateCreated, onRefresh, appMode = 'demo', onResetSandbox }) {
  const [showIssueModal, setShowIssueModal] = useState(false)
  const [showKillSwitchModal, setShowKillSwitchModal] = useState(false)
  const [showMandatePopover, setShowMandatePopover] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isAgentPaused, setIsAgentPaused] = useState(false)
  const [isTogglingPause, setIsTogglingPause] = useState(false)
  const [copiedHash, setCopiedHash] = useState(false)
  const [formErrors, setFormErrors] = useState({})

  const [formData, setFormData] = useState({
    owner_id: 'user_enterprise_buyer',
    agent_id: 'agent_demo_01',
    max_order_total: '1200.00',
    auto_approve_under: '1000.00',
    max_quantity: 1,
    ram: '16GB',
    storage: '512GB',
    allowed_domains: 'staples.com, bestbuy.com, newegg.com',
    expires_in_hours: 24,
  })

  const currentAgentId = mandate?.agent_id || 'agent_demo_01'

  useEffect(() => {
    const checkAgentStatus = async () => {
      try {
        const endpoint = appMode === 'demo'
          ? '/api/demo/agent-status'
          : `/api/agents/${currentAgentId}/status`
        const res = await fetch(endpoint)
        if (res.ok) {
          const data = await res.json()
          setIsAgentPaused(!!data.is_paused)
        }
      } catch (err) {
        console.error('Failed to query agent pause status:', err)
      }
    }
    checkAgentStatus()
  }, [currentAgentId, appMode])

  const executeKillSwitchToggle = async () => {
    setIsTogglingPause(true)
    try {
      let endpoint
      const headers = {}

      if (appMode === 'demo') {
        endpoint = isAgentPaused ? '/api/demo/resume' : '/api/demo/pause'
      } else {
        const key = window.prompt('Enter Admin API Key (held in memory only):')
        if (!key) {
          setIsTogglingPause(false)
          return
        }
        endpoint = isAgentPaused
          ? `/api/agents/${currentAgentId}/resume`
          : `/api/agents/${currentAgentId}/pause`
        headers['X-Admin-Key'] = key
      }

      const res = await fetch(endpoint, {
        method: 'POST',
        headers,
      })
      if (res.ok) {
        setIsAgentPaused(!isAgentPaused)
        setShowKillSwitchModal(false)
        if (onRefresh) onRefresh()
      } else {
        const data = await res.json()
        alert(data.detail || 'Failed to toggle kill switch')
      }
    } catch (err) {
      console.error('Error toggling kill switch:', err)
      alert('Error toggling agent kill switch')
    } finally {
      setIsTogglingPause(false)
    }
  }

  // Calculate live relative remaining time
  const getRemainingTimeDisplay = () => {
    if (!mandate?.expires_at) return 'expires in 24h'
    const diffMs = new Date(mandate.expires_at).getTime() - Date.now()
    if (diffMs <= 0) return 'expired'
    const totalMins = Math.floor(diffMs / 60000)
    const hours = Math.floor(totalMins / 60)
    const mins = totalMins % 60
    if (hours > 0) {
      return `expires in ${hours}h ${mins}m`
    }
    return `expires in ${mins}m`
  }

  const policyHash = mandate?.policy_hash || '2cbb8cc57c599e15831e389d759e22c329803da1ae772c87603f7cd8d2807d8c'
  const isRevoked = mandate?.status === 'REVOKED'
  const isExpired = mandate?.expires_at ? (new Date(mandate.expires_at).getTime() - Date.now() <= 0) : false

  const handleCopyHash = () => {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(policyHash)
      setCopiedHash(true)
      setTimeout(() => setCopiedHash(false), 2000)
    }
  }

  const validateForm = () => {
    const errors = {}
    if (!formData.owner_id.trim()) errors.owner_id = 'Owner ID is required.'
    if (!formData.agent_id.trim()) errors.agent_id = 'Agent ID is required.'
    if (isNaN(Number(formData.max_order_total)) || Number(formData.max_order_total) <= 0) {
      errors.max_order_total = 'Enter a valid positive dollar amount.'
    }
    if (isNaN(Number(formData.auto_approve_under)) || Number(formData.auto_approve_under) <= 0) {
      errors.auto_approve_under = 'Enter a valid threshold amount.'
    }
    if (Number(formData.auto_approve_under) > Number(formData.max_order_total)) {
      errors.auto_approve_under = 'Threshold cannot exceed max order total.'
    }
    if (Number(formData.max_quantity) < 1) {
      errors.max_quantity = 'Quantity must be at least 1.'
    }
    if (!formData.allowed_domains.trim()) {
      errors.allowed_domains = 'Specify at least one merchant domain.'
    }
    return errors
  }

  const handleCreateMandateSubmit = async (e) => {
    e.preventDefault()
    const errors = validateForm()
    setFormErrors(errors)
    if (Object.keys(errors).length > 0) return

    setIsSubmitting(true)
    try {
      if (appMode === 'demo') {
        alert('In demo mode, your session already has an isolated, Ed25519-signed mandate active. Custom root mandates require Admin Mode.')
        setShowIssueModal(false)
        return
      }

      const adminKey = window.prompt('Enter Admin API Key (held in memory only):')
      if (!adminKey) {
        setIsSubmitting(false)
        return
      }

      const payload = {
        owner_id: formData.owner_id,
        agent_id: formData.agent_id,
        max_order_total: formData.max_order_total,
        auto_approve_under: formData.auto_approve_under,
        max_quantity: Number(formData.max_quantity),
        required_attributes: {
          ram: formData.ram,
          storage: formData.storage,
        },
        allowed_domains: formData.allowed_domains.split(',').map((d) => d.trim()).filter(Boolean),
        required_availability: 'InStock',
        daily_limit: '2500.00',
        weekly_limit: '7500.00',
        per_merchant_limit: '1500.00',
        max_orders_per_hour: 10,
        expires_in_hours: Number(formData.expires_in_hours),
      }

      const res = await fetch('/api/mandates', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Key': adminKey,
        },
        body: JSON.stringify(payload),
      })
      const data = await res.json()
      if (res.ok && data.mandate) {
        if (onNewMandateCreated) {
          onNewMandateCreated(data.mandate)
        }
        setShowIssueModal(false)
      } else {
        alert(data.detail || 'Failed to create signed mandate')
      }
    } catch (err) {
      console.error('Error creating mandate:', err)
      alert('Error creating signed mandate')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <>
      <header className="header" role="banner">
        <div className="header-inner">
          {/* Left Brand Identity: Mark + Wordmark + Caption */}
          <div className="header-brand">
            <div className="brand-logo-mark" aria-hidden="true">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                <path
                  d="M12 2L3 6V11.5C3 16.5 6.8 21.1 12 22C17.2 21.1 21 16.5 21 11.5V6L12 2Z"
                  fill="#003087"
                />
                <path
                  d="M12 4.2L5 7.3V11.5C5 15.3 7.9 18.9 12 19.8C16.1 18.9 19 15.3 19 11.5V7.3L12 4.2Z"
                  fill="#0070E0"
                />
                <path
                  d="M10.5 14.5L7.5 11.5L8.9 10.1L10.5 11.7L15.1 7.1L16.5 8.5L10.5 14.5Z"
                  fill="#FFFFFF"
                />
              </svg>
            </div>
            <div className="brand-titles">
              <span className="brand-name">Intent</span>
              <span className="brand-caption">for PayPal Commerce</span>
            </div>
          </div>

          {/* Right Controls: [Sandbox] -> Compact Mandate -> [Issue mandate] -> [Kill switch] */}
          <div className="header-actions">
            {/* 1. Sandbox Label (rectangular tag, info style) */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span className="status-tag status-tag-info" data-testid="sandbox-tag">
                Sandbox
              </span>
              {appMode === 'demo' && onResetSandbox && (
                <button
                  type="button"
                  onClick={onResetSandbox}
                  title="Reset demo sandbox session and restore fresh quota"
                  style={{
                    background: 'none',
                    border: '1px solid #CBD3DF',
                    borderRadius: '4px',
                    padding: '2px 8px',
                    fontSize: '11px',
                    fontWeight: 500,
                    color: '#55627A',
                    cursor: 'pointer',
                  }}
                >
                  Reset
                </button>
              )}
            </div>

            {/* 2. Compact Mandate Status Button with Dot + Relative Expiry */}
            <div className="mandate-popover-wrapper">
              <button
                type="button"
                className="btn-mandate-status"
                onClick={() => setShowMandatePopover(!showMandatePopover)}
                aria-expanded={showMandatePopover}
                aria-label="View mandate security contract"
              >
                <span
                  className={`status-dot ${isRevoked ? 'dot-danger' : isAgentPaused ? 'dot-danger' : isExpired ? 'dot-danger' : 'dot-success'}`}
                  aria-hidden="true"
                />
                <span className="mandate-status-label">
                  {isRevoked ? 'Mandate revoked' : isAgentPaused ? 'Agent paused' : isExpired ? 'Mandate expired' : 'Mandate active'}
                </span>
                <span className="mandate-status-expiry">
                  &bull; {getRemainingTimeDisplay()}
                </span>
              </button>

              {/* Mandate Detail Popover */}
              {showMandatePopover && (
                <div className="mandate-popover-panel">
                  <div className="popover-header">
                    <span className="popover-title">Cryptographic mandate contract</span>
                    <button
                      type="button"
                      className="popover-close-btn"
                      onClick={() => setShowMandatePopover(false)}
                      aria-label="Close popover"
                    >
                      <X size={14} />
                    </button>
                  </div>

                  <div className="popover-body">
                    <div className="kv-row">
                      <span className="kv-key">Mandate ID</span>
                      <span className="kv-val font-mono">{mandate?.mandate_id || 'demo_mandate_01'}</span>
                    </div>
                    <div className="kv-row">
                      <span className="kv-key">Agent ID</span>
                      <span className="kv-val font-mono">{currentAgentId}</span>
                    </div>
                    <div className="kv-row">
                      <span className="kv-key">Signature</span>
                      <span className="status-tag status-tag-success">Ed25519 verified</span>
                    </div>
                    <div className="kv-row">
                      <span className="kv-key">Status / Expiry</span>
                      <span className={`status-tag ${isExpired ? 'status-tag-danger' : isRevoked ? 'status-tag-danger' : 'status-tag-success'}`}>
                        {isExpired ? 'Expired' : isRevoked ? 'Revoked' : getRemainingTimeDisplay()}
                      </span>
                    </div>
                    <div className="kv-row">
                      <span className="kv-key">Policy hash</span>
                      <div className="kv-val-hash">
                        <span className="font-mono text-ellipsis" title={policyHash}>
                          {`0x${policyHash.slice(0, 10)}…`}
                        </span>
                        <button
                          type="button"
                          className="btn-icon-copy"
                          onClick={handleCopyHash}
                          title="Copy full policy hash"
                        >
                          {copiedHash ? <Check size={13} color="var(--status-success)" /> : <Copy size={13} />}
                        </button>
                      </div>
                    </div>

                    <div className="popover-divider" />

                    <div className="kv-row">
                      <span className="kv-key">Max order budget</span>
                      <span className="kv-val font-mono tabular-nums">
                        ${Number(mandate?.max_order_total || policy?.max_order_total || 1200).toFixed(2)}
                      </span>
                    </div>
                    <div className="kv-row">
                      <span className="kv-key">Auto-approve threshold</span>
                      <span className="kv-val font-mono tabular-nums">
                        ${Number(mandate?.auto_approve_under || policy?.auto_approve_under || 1000).toFixed(2)}
                      </span>
                    </div>
                    <div className="kv-row">
                      <span className="kv-key">Max quantity</span>
                      <span className="kv-val font-mono tabular-nums">
                        {mandate?.max_quantity || policy?.max_quantity || 1}
                      </span>
                    </div>
                    <div className="kv-row">
                      <span className="kv-key">Required specs</span>
                      <span className="kv-val">RAM: 16GB &bull; Storage: 512GB</span>
                    </div>
                    <div className="kv-row">
                      <span className="kv-key">Merchant allowlist</span>
                      <span className="kv-val">staples.com, bestbuy.com, newegg.com</span>
                    </div>
                    <div className="kv-row">
                      <span className="kv-key">Cumulative limits</span>
                      <span className="kv-val font-mono tabular-nums">Daily $2,500 &bull; Weekly $7,500</span>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* 3. Secondary "Issue mandate" Button */}
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                setFormErrors({})
                setShowIssueModal(true)
              }}
              title="Issue a new cryptographic Ed25519 mandate"
            >
              Issue mandate
            </button>

            {/* 4. Destructive Outline "Kill switch" Button */}
            <button
              type="button"
              className={`btn btn-destructive-outline ${isAgentPaused ? 'is-paused' : ''}`}
              onClick={() => setShowKillSwitchModal(true)}
              title={
                isAgentPaused
                  ? `Resume agent '${currentAgentId}'`
                  : `Halt agent '${currentAgentId}' immediately`
              }
            >
              {isAgentPaused ? 'Resume agent' : 'Kill switch'}
            </button>
          </div>
        </div>
      </header>

      {/* Kill Switch Confirmation Modal (Small 440px modal, filled destructive button only here) */}
      {showKillSwitchModal && (
        <div className="modal-backdrop" onClick={() => setShowKillSwitchModal(false)}>
          <div
            className="modal-dialog kill-switch-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="kill-switch-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <h2 id="kill-switch-title" className="modal-title">
                {isAgentPaused ? 'Resume agent purchasing' : 'Confirm kill switch activation'}
              </h2>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowKillSwitchModal(false)}
                aria-label="Close dialog"
              >
                <X size={16} />
              </button>
            </div>

            <div className="modal-body-padded">
              <p className="modal-one-sentence">
                {isAgentPaused
                  ? `Resuming restores autonomous purchasing capabilities for '${currentAgentId}' under active mandate boundaries.`
                  : `Activating the kill switch immediately halts all autonomous purchasing for '${currentAgentId}' and rejects incoming payment intents.`}
              </p>
            </div>

            <div className="modal-footer">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setShowKillSwitchModal(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className={isAgentPaused ? 'btn btn-primary' : 'btn btn-destructive-solid'}
                onClick={executeKillSwitchToggle}
                disabled={isTogglingPause}
              >
                {isTogglingPause
                  ? 'Updating…'
                  : isAgentPaused
                  ? 'Resume agent'
                  : 'Activate kill switch'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Issue Mandate Modal (Centered 560px, 1px border, 8px radius, soft backdrop rgba(15,27,51,0.4) no blur) */}
      {showIssueModal && (
        <div className="modal-backdrop" onClick={() => setShowIssueModal(false)}>
          <div
            className="modal-dialog issue-mandate-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="issue-mandate-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header">
              <h2 id="issue-mandate-title" className="modal-title">
                Issue mandate
              </h2>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setShowIssueModal(false)}
                aria-label="Close dialog"
              >
                <X size={16} />
              </button>
            </div>

            <form onSubmit={handleCreateMandateSubmit} className="mandate-modal-form">
              <div className="modal-body-padded">
                <p className="modal-intro-text">
                  Issue an Ed25519-signed policy contract binding spending thresholds, hardware specifications, and merchant allowlists to an agent identity.
                </p>

                {/* Two-Column Grid */}
                <div className="modal-two-col-grid">
                  {/* Owner ID */}
                  <div className="form-field-group">
                    <label htmlFor="owner-id" className="field-label">Owner ID</label>
                    <input
                      id="owner-id"
                      type="text"
                      className="form-input"
                      value={formData.owner_id}
                      onChange={(e) => setFormData({ ...formData, owner_id: e.target.value })}
                    />
                    <span className="field-helper">Enterprise identity owning this policy.</span>
                    {formErrors.owner_id && (
                      <span className="field-error">
                        <AlertCircle size={12} aria-hidden="true" />
                        <span>{formErrors.owner_id}</span>
                      </span>
                    )}
                  </div>

                  {/* Agent ID */}
                  <div className="form-field-group">
                    <label htmlFor="agent-id" className="field-label">Agent ID</label>
                    <input
                      id="agent-id"
                      type="text"
                      className="form-input"
                      value={formData.agent_id}
                      onChange={(e) => setFormData({ ...formData, agent_id: e.target.value })}
                    />
                    <span className="field-helper">Target autonomous agent identifier.</span>
                    {formErrors.agent_id && (
                      <span className="field-error">
                        <AlertCircle size={12} aria-hidden="true" />
                        <span>{formErrors.agent_id}</span>
                      </span>
                    )}
                  </div>

                  {/* Max Order Total */}
                  <div className="form-field-group">
                    <label htmlFor="max-order" className="field-label">Max order total (USD)</label>
                    <input
                      id="max-order"
                      type="text"
                      className="form-input font-mono"
                      value={formData.max_order_total}
                      onChange={(e) => setFormData({ ...formData, max_order_total: e.target.value })}
                    />
                    <span className="field-helper">Absolute hard cap per single order.</span>
                    {formErrors.max_order_total && (
                      <span className="field-error">
                        <AlertCircle size={12} aria-hidden="true" />
                        <span>{formErrors.max_order_total}</span>
                      </span>
                    )}
                  </div>

                  {/* Auto-Approve Threshold */}
                  <div className="form-field-group">
                    <label htmlFor="auto-approve" className="field-label">Auto-approve threshold (USD)</label>
                    <input
                      id="auto-approve"
                      type="text"
                      className="form-input font-mono"
                      value={formData.auto_approve_under}
                      onChange={(e) => setFormData({ ...formData, auto_approve_under: e.target.value })}
                    />
                    <span className="field-helper">Orders exceeding this require supervisor token.</span>
                    {formErrors.auto_approve_under && (
                      <span className="field-error">
                        <AlertCircle size={12} aria-hidden="true" />
                        <span>{formErrors.auto_approve_under}</span>
                      </span>
                    )}
                  </div>

                  {/* Max Quantity */}
                  <div className="form-field-group">
                    <label htmlFor="max-qty" className="field-label">Max quantity</label>
                    <input
                      id="max-qty"
                      type="number"
                      min="1"
                      className="form-input font-mono"
                      value={formData.max_quantity}
                      onChange={(e) => setFormData({ ...formData, max_quantity: e.target.value })}
                    />
                    <span className="field-helper">Maximum items allowed per transaction.</span>
                    {formErrors.max_quantity && (
                      <span className="field-error">
                        <AlertCircle size={12} aria-hidden="true" />
                        <span>{formErrors.max_quantity}</span>
                      </span>
                    )}
                  </div>

                  {/* Validity Window */}
                  <div className="form-field-group">
                    <label htmlFor="expires-hours" className="field-label">Validity window (hours)</label>
                    <input
                      id="expires-hours"
                      type="number"
                      min="1"
                      className="form-input font-mono"
                      value={formData.expires_in_hours}
                      onChange={(e) => setFormData({ ...formData, expires_in_hours: e.target.value })}
                    />
                    <span className="field-helper">Cryptographic expiry duration.</span>
                  </div>

                  {/* Allowed Domains (full width across 2 cols) */}
                  <div className="form-field-group grid-span-2">
                    <label htmlFor="allowed-domains" className="field-label">Allowed merchant domains</label>
                    <input
                      id="allowed-domains"
                      type="text"
                      className="form-input"
                      value={formData.allowed_domains}
                      onChange={(e) => setFormData({ ...formData, allowed_domains: e.target.value })}
                    />
                    <span className="field-helper">Comma-separated domain list (e.g. staples.com, bestbuy.com).</span>
                    {formErrors.allowed_domains && (
                      <span className="field-error">
                        <AlertCircle size={12} aria-hidden="true" />
                        <span>{formErrors.allowed_domains}</span>
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Footer with Cancel and Issue mandate aligned right */}
              <div className="modal-footer">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setShowIssueModal(false)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={isSubmitting}
                >
                  {isSubmitting ? 'Signing…' : 'Issue mandate'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  )
}
