import React from 'react'
import { Shield, Zap, Sparkles, Lock, ExternalLink } from 'lucide-react'

export default function Header({ policy, rateLimitStatus, health }) {
  return (
    <header className="paypal-global-header">
      {/* Top Global Navigation Bar */}
      <div className="paypal-nav-container">
        <div className="paypal-nav-left">
          {/* Authentic PayPal Logo */}
          <div className="paypal-brand-mark">
            <svg width="26" height="30" viewBox="0 0 28 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label="PayPal Logo">
              <path d="M23.14 8.78c-.46-3.23-2.82-5.45-6.72-5.45H6.28c-.8 0-1.47.6-1.59 1.4L1.03 27.87c-.1.65.4 1.23 1.05 1.23h5.27l1.32-8.38-.04.26c.12-.8.8-1.4 1.6-1.4h2.52c5.07 0 9.04-2.06 10.2-8.08.06-.33.11-.66.15-.99.3-1.87.11-3.2-.96-4.73z" fill="#003087"/>
              <path d="M26.4 11.23c-.38 2.45-1.54 4.54-3.4 5.92-2.12 1.57-5.06 2.37-8.73 2.37h-2.11c-.74 0-1.37.55-1.48 1.29l-1.63 10.33c-.08.53.33 1.01.87 1.01h4.63c.66 0 1.21-.5 1.32-1.15l.05-.27 1.05-6.66.07-.38c.11-.66.66-1.15 1.32-1.15h.83c4.22 0 7.52-1.71 8.49-6.72.4-2.09.2-3.77-.96-4.99z" fill="#0070E0"/>
            </svg>
            <span className="paypal-wordmark">PayPal</span>
            <span className="brand-sep">/</span>
            <span className="brand-product-name">Intent</span>
            <span className="brand-suite-pill">AI Firewall</span>
          </div>

          {/* PayPal Top Menu Links */}
          <nav className="paypal-top-nav-links" aria-label="Main Navigation">
            <span className="nav-link active">Firewall Engine</span>
            <span className="nav-link">Deterministic Policy</span>
            <span className="nav-link">Security Ledger</span>
            <a
              href="https://developer.paypal.com"
              target="_blank"
              rel="noreferrer"
              className="nav-link external"
            >
              <span>Developer Docs</span>
              <ExternalLink size={12} />
            </a>
          </nav>
        </div>

        {/* Right CTA / Status Action Group */}
        <div className="paypal-nav-right">
          <div className="nav-status-pills">
            <div className="status-pill">
              <span className="status-dot green"></span>
              <span className="status-label">Sandbox:</span>
              <span className="status-value">{health?.paypal_configured ? 'Ready' : 'Standby'}</span>
            </div>

            <div className="status-pill">
              <span className="status-dot blue"></span>
              <span className="status-label">Channel3:</span>
              <span className="status-value">{health?.channel3_configured ? 'Live API' : 'Cache'}</span>
            </div>

            <div className="status-pill quota-pill">
              <Zap size={12} className="text-warning" />
              <span className="status-value font-mono">
                {rateLimitStatus ? `${rateLimitStatus.channel3_calls_today}/${rateLimitStatus.channel3_daily_cap}` : '0/250'}
              </span>
            </div>
          </div>

          <div className="header-action-buttons">
            <button type="button" className="btn-paypal-secondary">
              Policy Docs
            </button>
            <button type="button" className="btn-paypal-primary">
              Live Console
            </button>
          </div>
        </div>
      </div>

      {/* Subheader: Active Policy Ribbon (Clean Human Language) */}
      <div className="paypal-subnav-strip">
        <div className="subnav-inner">
          <div className="subnav-title-group">
            <div className="subnav-badge">
              <Lock size={13} className="text-paypal-blue" />
              <span>Deterministic Enforcement</span>
            </div>
            <span className="subnav-headline">
              Fail-closed pure-code verification before funds move to PayPal Sandbox.
            </span>
          </div>

          <div className="policy-chips-container">
            <div className="policy-chip">
              <span className="chip-key">Spending Limit</span>
              <span className="chip-val">${policy?.max_order_total || '1,200.00'}</span>
            </div>

            <div className="policy-chip">
              <span className="chip-key">Max Qty</span>
              <span className="chip-val">{policy?.max_quantity || 1} Unit</span>
            </div>

            <div className="policy-chip">
              <span className="chip-key">Required Specs</span>
              <span className="chip-val">
                {policy?.required_structured_attributes?.ram || '16GB'} RAM · {policy?.required_structured_attributes?.storage || '512GB'} SSD
              </span>
            </div>

            <div className="policy-chip highlight">
              <span className="chip-key">Auto-Capture</span>
              <span className="chip-val text-success">
                &le; ${policy?.auto_approve_under || '1,000.00'}
              </span>
            </div>

            <div className="policy-chip">
              <span className="chip-key">Inventory</span>
              <span className="chip-val">{policy?.required_availability || 'InStock'}</span>
            </div>
          </div>
        </div>
      </div>
    </header>
  )
}
