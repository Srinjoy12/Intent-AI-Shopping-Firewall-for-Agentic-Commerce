import React from 'react'
import { Shield, CheckCircle, Zap, Sparkles } from 'lucide-react'

export default function Header({ policy, rateLimitStatus, health }) {
  return (
    <header className="header-container">
      {/* Top Navbar */}
      <div className="header-top">
        <div className="brand-group">
          <div className="paypal-logo-badge">
            <span className="paypal-p-symbol">P</span>
          </div>
          <div>
            <div className="brand-title-row">
              <span className="brand-org">PayPal</span>
              <span className="brand-divider">/</span>
              <h1 className="brand-title">Intent</h1>
              <span className="brand-badge">Firewall</span>
            </div>
            <p className="brand-subtitle">
              Deterministic pure-code guardrail enforcing spending limits, quantities, and verified specs before funds move.
            </p>
          </div>
        </div>

        <div className="header-status-group">
          <div className="status-pill">
            <span className="status-dot green"></span>
            <span className="status-label">PayPal Sandbox:</span>
            <span className="status-value">{health?.paypal_configured ? 'Ready' : 'Standby'}</span>
          </div>

          <div className="status-pill">
            <span className="status-dot blue"></span>
            <span className="status-label">Channel3:</span>
            <span className="status-value">{health?.channel3_configured ? 'Live API' : 'Fixture Cache'}</span>
          </div>

          <div className="status-pill">
            <Shield size={13} className="text-paypal-blue" />
            <span className="status-label">Trust Boundary:</span>
            <span className="status-value">Isolated Agent</span>
          </div>

          {rateLimitStatus && (
            <div className="status-pill">
              <Zap size={13} className="text-warning" />
              <span className="status-label">API Quota:</span>
              <span className="status-value font-mono">
                {rateLimitStatus.channel3_calls_today}/{rateLimitStatus.channel3_daily_cap}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Clean Human Policy Bar */}
      <div className="policy-strip">
        <div className="policy-badge-title">
          <Sparkles size={14} className="text-paypal-blue" />
          <span>Active Defense Rules</span>
        </div>

        <div className="policy-items">
          <div className="policy-item">
            <span className="policy-label">Spending Limit:</span>
            <span className="policy-val">${policy?.max_order_total || '1,200.00'}</span>
          </div>

          <span className="policy-sep">•</span>

          <div className="policy-item">
            <span className="policy-label">Max Quantity:</span>
            <span className="policy-val">{policy?.max_quantity || 1} Unit</span>
          </div>

          <span className="policy-sep">•</span>

          <div className="policy-item">
            <span className="policy-label">Required Specs:</span>
            <span className="policy-val">
              {policy?.required_structured_attributes?.ram || '16GB'} RAM, {policy?.required_structured_attributes?.storage || '512GB'} SSD
            </span>
          </div>

          <span className="policy-sep">•</span>

          <div className="policy-item">
            <span className="policy-label">Auto-Capture:</span>
            <span className="policy-val text-success">
              &le; ${policy?.auto_approve_under || '1,000.00'}
            </span>
          </div>

          <span className="policy-sep">•</span>

          <div className="policy-item">
            <span className="policy-label">Stock Status:</span>
            <span className="policy-val">{policy?.required_availability || 'InStock'}</span>
          </div>
        </div>
      </div>
    </header>
  )
}
