import React from 'react'
import { Shield, ShieldAlert, Zap, Cpu, Server, CheckCircle2, AlertCircle } from 'lucide-react'

export default function Header({ policy, rateLimitStatus, health }) {
  return (
    <header className="header-container">
      {/* Top Navbar */}
      <div className="header-top">
        <div className="brand-group">
          <div className="brand-logo">
            <Shield className="brand-icon" size={24} />
          </div>
          <div>
            <div className="brand-title-row">
              <h1 className="brand-title">INTENT</h1>
              <span className="brand-badge">AI SHOPPING FIREWALL</span>
            </div>
            <p className="brand-subtitle">
              Deterministic 4-rule gate enforcing spending limits, quantities, and structured product attributes before PayPal transactions.
            </p>
          </div>
        </div>

        <div className="header-status-group">
          <div className="status-pill">
            <span className="status-dot green"></span>
            <span className="status-label">PayPal Sandbox:</span>
            <span className="status-value">{health?.paypal_configured ? 'CONNECTED' : 'STANDBY'}</span>
          </div>

          <div className="status-pill">
            <span className="status-dot blue"></span>
            <span className="status-label">Channel3:</span>
            <span className="status-value">{health?.channel3_configured ? 'ACTIVE' : 'FIXTURES'}</span>
          </div>

          <div className="status-pill">
            <Cpu size={14} className="status-icon" />
            <span className="status-label">Agent:</span>
            <span className="status-value font-mono">UNTRUSTED (ISOLATED)</span>
          </div>

          {rateLimitStatus && (
            <div className="status-pill">
              <Zap size={14} className="status-icon" />
              <span className="status-label">Quotas:</span>
              <span className="status-value font-mono">
                C3 {rateLimitStatus.channel3_calls_today}/{rateLimitStatus.channel3_daily_cap}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Real-time Policy Strip */}
      <div className="policy-strip">
        <div className="policy-badge-title">
          <Server size={14} />
          <span>SERVER POLICY ({policy?.policy_id || 'pol_demo_01'})</span>
        </div>

        <div className="policy-items">
          <div className="policy-item">
            <span className="policy-label">BUDGET CAP:</span>
            <span className="policy-val font-mono">${policy?.max_order_total || '1,200.00'} USD</span>
          </div>

          <div className="policy-divider">/</div>

          <div className="policy-item">
            <span className="policy-label">MAX QUANTITY:</span>
            <span className="policy-val font-mono">{policy?.max_quantity || 1} UNIT</span>
          </div>

          <div className="policy-divider">/</div>

          <div className="policy-item">
            <span className="policy-label">REQUIRED ATTRIBUTES:</span>
            <span className="policy-val font-mono">
              ram={policy?.required_structured_attributes?.ram || '16GB'}, storage={policy?.required_structured_attributes?.storage || '512GB'}
            </span>
          </div>

          <div className="policy-divider">/</div>

          <div className="policy-item">
            <span className="policy-label">AUTO-APPROVE:</span>
            <span className="policy-val font-mono font-semibold text-emerald-400">
              &le; ${policy?.auto_approve_under || '1,000.00'} USD
            </span>
          </div>

          <div className="policy-divider">/</div>

          <div className="policy-item">
            <span className="policy-label">REQUIRED AVAILABILITY:</span>
            <span className="policy-val font-mono">{policy?.required_availability || 'InStock'}</span>
          </div>
        </div>
      </div>
    </header>
  )
}
