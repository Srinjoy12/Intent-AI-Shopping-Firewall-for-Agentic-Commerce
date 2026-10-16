import React from 'react'
import { Shield, Zap, Sparkles, Lock, ExternalLink } from 'lucide-react'

export default function Header({ policy, rateLimitStatus, health }) {
  return (
    <header className="paypal-global-header">
      {/* Top Global Navigation Bar */}
      <div className="paypal-nav-container">
        <div className="paypal-nav-left">
          {/* Distinctive Intent Brand Mark */}
          <div className="paypal-brand-mark">
            <svg width="30" height="30" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label="Intent Shield Logo">
              <rect width="32" height="32" rx="8" fill="#001C64"/>
              <path d="M16 5L7 9.2V16.8C7 22.3 10.8 27.4 16 29C21.2 27.4 25 22.3 25 16.8V9.2L16 5Z" fill="#003087" stroke="#0070E0" strokeWidth="1.5"/>
              <path d="M16 9L11 11.5V16C11 19.8 13.1 23.3 16 24.5C18.9 23.3 21 19.8 21 16V11.5L16 9Z" fill="#0070E0" opacity="0.6"/>
              <path d="M14 16.5L16 18.5L20 13.5" stroke="#FFD140" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            <span className="brand-product-name" style={{ fontSize: '20px', fontWeight: 800, color: '#001C64', letterSpacing: '-0.5px' }}>Intent</span>
            <span className="brand-suite-pill">AI Shopping Firewall</span>
            <span className="partner-integration-chip">for PayPal Commerce</span>
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
