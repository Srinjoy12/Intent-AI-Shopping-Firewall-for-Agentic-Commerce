import React, { useState } from 'react'
import {
  BarChart3,
  ShieldAlert,
  ShieldCheck,
  CheckCircle,
  RotateCcw,
  Search,
  Filter,
  Layers,
  Database,
  ArrowUpDown,
} from 'lucide-react'

export default function AnalyticsDashboard({ analytics, attempts, onRefresh }) {
  const [filterStatus, setFilterStatus] = useState('ALL')
  const [searchTerm, setSearchTerm] = useState('')

  const summary = analytics?.summary || {
    total_attempts: 0,
    blocked_count: 0,
    verified_count: 0,
    captured_count: 0,
    refunded_count: 0,
    violation_breakdown: {},
  }

  // Filter attempts
  const filteredAttempts = attempts.filter((att) => {
    const matchesStatus = filterStatus === 'ALL' || att.status === filterStatus
    const term = searchTerm.toLowerCase()
    const matchesSearch =
      !term ||
      att.attempt_id?.toLowerCase().includes(term) ||
      att.product_id?.toLowerCase().includes(term) ||
      att.product_title?.toLowerCase().includes(term) ||
      att.merchant_domain?.toLowerCase().includes(term)
    return matchesStatus && matchesSearch
  })

  // Format date
  const formatTime = (isoString) => {
    if (!isoString) return '-'
    try {
      const d = new Date(isoString)
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    } catch {
      return isoString.slice(11, 19)
    }
  }

  return (
    <div className="analytics-dashboard-container">
      <div className="analytics-header">
        <div className="analytics-header-left">
          <Layers size={18} className="analytics-icon" />
          <div>
            <h2 className="analytics-title">AG STUDIO // GATEWAY ANALYTICS & THREAT AUDIT</h2>
            <p className="analytics-subtitle">
              Real-time audit log of deterministic firewall decisions and PayPal settlements.
            </p>
          </div>
        </div>

        <button type="button" className="btn-refresh-analytics" onClick={onRefresh}>
          <RotateCcw size={14} />
          <span>Refresh Data</span>
        </button>
      </div>

      {/* KPI Metric Cards */}
      <div className="kpi-grid">
        <div className="kpi-card">
          <span className="kpi-label">TOTAL ATTEMPTS</span>
          <div className="kpi-val-row">
            <span className="kpi-val font-mono">{summary.total_attempts}</span>
          </div>
          <span className="kpi-sub">Interception Invocations</span>
        </div>

        <div className="kpi-card danger">
          <span className="kpi-label">BLOCKED THREATS</span>
          <div className="kpi-val-row">
            <ShieldAlert size={20} className="text-danger" />
            <span className="kpi-val text-danger font-mono">{summary.blocked_count}</span>
          </div>
          <span className="kpi-sub">Fail-Closed Interceptions</span>
        </div>

        <div className="kpi-card accent">
          <span className="kpi-label">VERIFIED APPROVED</span>
          <div className="kpi-val-row">
            <ShieldCheck size={20} className="text-accent" />
            <span className="kpi-val text-accent font-mono">{summary.verified_count}</span>
          </div>
          <span className="kpi-sub">Cleared for PayPal Checkout</span>
        </div>

        <div className="kpi-card success">
          <span className="kpi-label">CAPTURED ORDERS</span>
          <div className="kpi-val-row">
            <CheckCircle size={20} className="text-success" />
            <span className="kpi-val text-success font-mono">{summary.captured_count}</span>
          </div>
          <span className="kpi-sub">Sandbox Funds Settled</span>
        </div>
      </div>

      {/* Violation Breakdown Strip */}
      <div className="violation-breakdown-card">
        <div className="breakdown-header">
          <BarChart3 size={15} />
          <h4>Rule Violation Breakdown</h4>
        </div>

        <div className="breakdown-bars">
          {Object.keys(summary.violation_breakdown || {}).length > 0 ? (
            Object.entries(summary.violation_breakdown).map(([rule, count]) => {
              const pct = summary.total_attempts
                ? Math.round((count / summary.total_attempts) * 100)
                : 0
              return (
                <div key={rule} className="breakdown-item">
                  <div className="breakdown-item-header font-mono">
                    <span className="rule-key">{rule}</span>
                    <span className="rule-count">{count} hit(s) ({pct}%)</span>
                  </div>
                  <div className="progress-track">
                    <div className="progress-fill" style={{ width: `${Math.min(pct, 100)}%` }}></div>
                  </div>
                </div>
              )
            })
          ) : (
            <span className="empty-breakdown-note">No violations recorded yet. Run presets to populate.</span>
          )}
        </div>
      </div>

      {/* AG Grid Style Attempt Log Table */}
      <div className="ag-grid-wrapper">
        <div className="table-controls-bar">
          <div className="table-search">
            <Search size={14} className="search-icon" />
            <input
              type="text"
              placeholder="Search by attempt ID, SKU, domain..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="search-input"
            />
          </div>

          <div className="table-filters">
            <Filter size={14} className="filter-icon" />
            <div className="filter-buttons">
              {['ALL', 'BLOCKED', 'VERIFIED_READY_FOR_PAYPAL', 'CAPTURED'].map((st) => (
                <button
                  key={st}
                  type="button"
                  className={`filter-btn ${filterStatus === st ? 'active' : ''}`}
                  onClick={() => setFilterStatus(st)}
                >
                  {st.replace(/_/g, ' ')}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="table-scroll-container">
          <table className="ag-data-table">
            <thead>
              <tr>
                <th>TIME</th>
                <th>ATTEMPT ID</th>
                <th>PRODUCT SKU / TITLE</th>
                <th>RETAILER</th>
                <th>QTY</th>
                <th>SUBTOTAL</th>
                <th>STATUS</th>
                <th>VIOLATIONS DETECTED</th>
                <th>PAYPAL ORDER</th>
              </tr>
            </thead>
            <tbody>
              {filteredAttempts.length > 0 ? (
                filteredAttempts.map((item) => {
                  const isBlk = item.status === 'BLOCKED'
                  const isCap = item.status === 'CAPTURED'
                  const isVer = item.status === 'VERIFIED_READY_FOR_PAYPAL'

                  return (
                    <tr key={item.id || item.attempt_id} className={isBlk ? 'row-blocked' : ''}>
                      <td className="font-mono text-muted">{formatTime(item.timestamp)}</td>
                      <td className="font-mono">{item.attempt_id}</td>
                      <td>
                        <div className="product-cell">
                          <span className="sku-tag font-mono">{item.product_id}</span>
                          <span className="sku-title">{item.product_title || '-'}</span>
                        </div>
                      </td>
                      <td className="font-mono">{item.merchant_domain}</td>
                      <td className="font-mono">{item.quantity}</td>
                      <td className="font-mono font-bold">
                        ${item.computed_subtotal || item.unit_price || '0.00'}
                      </td>
                      <td>
                        <span
                          className={`status-chip font-mono ${
                            isBlk ? 'chip-blocked' : isCap ? 'chip-captured' : 'chip-verified'
                          }`}
                        >
                          {item.status}
                        </span>
                      </td>
                      <td>
                        {item.violations && item.violations.length > 0 ? (
                          <div className="violations-tags">
                            {item.violations.map((v, idx) => (
                              <span key={idx} className="violation-pill font-mono">
                                {v.rule}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="no-violations font-mono">None (Compliant)</span>
                        )}
                      </td>
                      <td className="font-mono text-muted">
                        {item.paypal_order_id ? (
                          <span className="paypal-id-link font-mono">{item.paypal_order_id}</span>
                        ) : (
                          '-'
                        )}
                      </td>
                    </tr>
                  )
                })
              ) : (
                <tr>
                  <td colSpan={9} className="table-empty-row">
                    No matching attempts found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
