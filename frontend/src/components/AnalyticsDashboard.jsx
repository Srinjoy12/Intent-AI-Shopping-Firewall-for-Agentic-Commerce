import React, { useState, useMemo, useEffect } from 'react'
import { AgGridReact } from 'ag-grid-react'
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community'
import { CheckCircle2, XCircle, Clock, X, Copy, Check } from 'lucide-react'

ModuleRegistry.registerModules([AllCommunityModule])

const gridTheme = themeQuartz.withParams({
  backgroundColor: '#FFFFFF',
  headerBackgroundColor: '#F6F8FA',
  headerTextColor: '#55627A',
  headerFontSize: 12,
  headerFontWeight: 500,
  foregroundColor: '#0F1B33',
  borderColor: '#E3E8EF',
  rowHoverColor: '#F6F8FA',
  selectedRowBackgroundColor: '#E8F1FD',
  fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  fontSize: 13,
})

function HashCell({ fullHash }) {
  const [copied, setCopied] = useState(false)
  if (!fullHash || fullHash === '—') {
    return <span className="text-secondary font-mono text-xs">—</span>
  }
  const short = fullHash.length > 8 ? fullHash.slice(0, 8) : fullHash

  const handleCopy = (e) => {
    e.stopPropagation()
    if (navigator.clipboard) {
      navigator.clipboard.writeText(fullHash)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }
  }

  return (
    <div className="hash-cell-wrapper" onClick={handleCopy} title={`Copy full hash: ${fullHash}`}>
      <span className="font-mono text-xs text-primary tabular-nums">{short}</span>
      <button
        type="button"
        className="btn-icon-subtle hash-copy-btn"
        aria-label="Copy hash"
        onClick={handleCopy}
      >
        {copied ? <Check size={12} color="var(--status-success)" /> : <Copy size={12} />}
      </button>
    </div>
  )
}

export default function AnalyticsDashboard({ analytics, attempts = [], onRefresh, appMode = 'demo', onSwitchTab }) {
  const [filterStatus, setFilterStatus] = useState('ALL')
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedAttempt, setSelectedAttempt] = useState(null)
  const [chainVerification, setChainVerification] = useState(null)
  const [verifying, setVerifying] = useState(false)
  const [pendingApprovals, setPendingApprovals] = useState([])
  const [resolvingId, setResolvingId] = useState(null)
  const [copiedFullHash, setCopiedFullHash] = useState(false)

  const summary = analytics?.summary || {
    total_attempts: 0,
    blocked_count: 0,
    captured_count: 0,
    dollars_prevented: 0,
    dollars_captured: 0,
  }

  const fetchPendingApprovals = async () => {
    try {
      const endpoint = appMode === 'demo'
        ? '/api/demo/approvals/pending'
        : '/api/approvals/pending'
      const res = await fetch(endpoint)
      if (res.ok) {
        const data = await res.json()
        setPendingApprovals(Array.isArray(data) ? data : [])
      } else {
        setPendingApprovals([])
      }
    } catch (err) {
      console.warn('Pending approvals note:', err)
      setPendingApprovals([])
    }
  }

  const handleResolvePending = async (approvalId, action) => {
    setResolvingId(approvalId)
    try {
      let endpoint
      const headers = { 'Content-Type': 'application/json' }

      if (appMode === 'demo') {
        endpoint = `/api/demo/approvals/${approvalId}/resolve`
      } else {
        const adminKey = window.prompt('Enter Admin API Key (held in memory only):')
        if (!adminKey) {
          setResolvingId(null)
          return
        }
        endpoint = `/api/approvals/${approvalId}/resolve`
        headers['X-Admin-Key'] = adminKey
      }

      const res = await fetch(endpoint, {
        method: 'POST',
        headers,
        body: JSON.stringify({ action }),
      })
      if (res.ok) {
        await fetchPendingApprovals()
        if (onRefresh) onRefresh()
      } else {
        const data = await res.json()
        alert(data.detail || data.message || 'Failed to resolve approval')
      }
    } catch (err) {
      console.error('Error resolving approval:', err)
      alert('Error resolving approval: ' + err.message)
    } finally {
      setResolvingId(null)
    }
  }

  const handleVerifyChain = async () => {
    setVerifying(true)
    try {
      const res = await fetch('/api/audit/verify')
      const data = await res.json()
      setChainVerification(data)
    } catch (err) {
      console.error('Audit verification error:', err)
      setChainVerification({ valid: false, message: 'Failed to verify chain: ' + err.message })
    } finally {
      setVerifying(false)
    }
  }

  const handleExportAudit = async () => {
    try {
      const adminKey = window.prompt('Enter Admin API Key to export cryptographic audit manifest:')
      if (!adminKey) return

      const res = await fetch('/api/audit/export', {
        headers: { 'X-Admin-Key': adminKey },
      })
      if (!res.ok) {
        throw new Error('Export failed: ' + res.statusText)
      }
      const data = await res.json()
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `intent_audit_export_${new Date().toISOString().slice(0, 10)}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err) {
      alert('Audit export error: ' + err.message)
    }
  }

  useEffect(() => {
    handleVerifyChain()
    fetchPendingApprovals()
  }, [attempts])

  const formatTime = (isoString) => {
    if (!isoString) return '-'
    try {
      return new Date(isoString).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    } catch {
      return isoString.slice(11, 19)
    }
  }

  const rowData = useMemo(() => {
    return (attempts || []).filter((att) => {
      const statusVal = att.status || (att.needs_human_approval ? 'PENDING' : 'CAPTURED')
      const matchesStatus =
        filterStatus === 'ALL' ||
        statusVal === filterStatus ||
        (filterStatus === 'PENDING' && (statusVal === 'PENDING_APPROVAL' || att.needs_human_approval))
      const term = searchTerm.toLowerCase().trim()
      const matchesSearch =
        !term ||
        att.attempt_id?.toLowerCase().includes(term) ||
        att.product_title?.toLowerCase().includes(term) ||
        att.merchant_domain?.toLowerCase().includes(term) ||
        att.audit_event_hash?.toLowerCase().includes(term)
      return matchesStatus && matchesSearch
    })
  }, [attempts, filterStatus, searchTerm])

  const columnDefs = useMemo(
    () => [
      {
        field: 'timestamp',
        headerName: 'Time',
        width: 100,
        valueFormatter: (p) => formatTime(p.value),
        sort: 'desc',
        cellStyle: { color: 'var(--text-secondary)', fontVariantNumeric: 'tabular-nums', fontFamily: 'var(--font-mono)' },
      },
      {
        field: 'audit_event_hash',
        headerName: 'Block hash',
        width: 120,
        cellRenderer: (p) => <HashCell fullHash={p.value} />,
      },
      {
        field: 'product_title',
        headerName: 'Target item',
        flex: 1.5,
        minWidth: 180,
        cellRenderer: (p) => (
          <span style={{ fontWeight: 500, color: 'var(--text-primary)' }}>
            {p.value || p.data.product_id}
          </span>
        ),
      },
      {
        field: 'merchant_domain',
        headerName: 'Merchant',
        width: 130,
        cellStyle: { color: 'var(--text-secondary)' },
      },
      {
        field: 'computed_subtotal',
        headerName: 'Amount',
        width: 110,
        headerClass: 'ag-right-aligned-header',
        cellStyle: { textAlign: 'right', display: 'flex', justifyContent: 'flex-end', alignItems: 'center' },
        cellRenderer: (p) => (
          <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 500, fontVariantNumeric: 'tabular-nums', color: 'var(--text-primary)' }}>
            ${Number(p.value || p.data.unit_price || 0).toFixed(2)}
          </span>
        ),
      },
      {
        field: 'status',
        headerName: 'Decision',
        width: 130,
        cellRenderer: (p) => {
          const val = p.value || (p.data.needs_human_approval ? 'PENDING' : 'CAPTURED')
          if (val === 'BLOCKED') {
            return (
              <span className="status-tag status-tag-danger">
                <XCircle size={12} aria-hidden="true" />
                <span>Blocked</span>
              </span>
            )
          }
          if (val === 'PENDING' || val === 'PENDING_APPROVAL' || p.data.needs_human_approval) {
            return (
              <span className="status-tag status-tag-warning">
                <Clock size={12} aria-hidden="true" />
                <span>Pending</span>
              </span>
            )
          }
          if (val === 'DENIED') {
            return (
              <span className="status-tag status-tag-danger">
                <XCircle size={12} aria-hidden="true" />
                <span>Denied</span>
              </span>
            )
          }
          return (
            <span className="status-tag status-tag-success">
              <CheckCircle2 size={12} aria-hidden="true" />
              <span>{val === 'APPROVED' ? 'Approved' : 'Captured'}</span>
            </span>
          )
        },
      },
      {
        field: 'violations',
        headerName: 'Enforcement detail',
        flex: 1.5,
        minWidth: 200,
        cellRenderer: (p) => {
          const viols = p.value || []
          if (p.data.needs_human_approval || p.data.status === 'PENDING_APPROVAL') {
            return <span style={{ color: 'var(--status-warning)', fontSize: '12px' }}>Held for supervisor authorization</span>
          }
          if (viols.length === 0) {
            return <span style={{ color: 'var(--status-success)', fontSize: '12px' }}>Clean compliance (4/4 passed)</span>
          }
          return (
            <span style={{ color: 'var(--status-danger)', fontSize: '12px' }}>
              {viols.map((v) => v.detail || v.rule).join(' · ')}
            </span>
          )
        },
      },
    ],
    []
  )

  const defaultColDef = useMemo(
    () => ({
      sortable: true,
      filter: true,
      resizable: true,
      suppressCellFocus: true,
    }),
    []
  )

  return (
    <div className="analytics-page-wrapper">
      {/* 1. Top Row: 4 KPI Figures in ONE Flat Bordered Panel Separated by Vertical Dividers */}
      <div className="panel kpi-ledger-panel">
        <div className="kpi-ledger-grid">
          <div className="kpi-ledger-cell">
            <span className="kpi-ledger-num">{summary.total_attempts}</span>
            <span className="kpi-ledger-label">Total requests</span>
          </div>
          <div className="kpi-ledger-cell">
            <span className="kpi-ledger-num text-danger">{summary.blocked_count}</span>
            <span className="kpi-ledger-label">Blocked</span>
          </div>
          <div className="kpi-ledger-cell">
            <span className="kpi-ledger-num text-success">{summary.captured_count}</span>
            <span className="kpi-ledger-label">Captured</span>
          </div>
          <div className="kpi-ledger-cell">
            <span className="kpi-ledger-num text-danger">${Number(summary.dollars_prevented || 0).toFixed(2)}</span>
            <span className="kpi-ledger-label">Blocked attempt value</span>
          </div>
        </div>
      </div>

      {/* Pending Approvals Strip (when items pending) */}
      {pendingApprovals.length > 0 && (
        <div className="pending-approvals-panel">
          <div className="pending-approvals-header">
            <Clock size={16} color="var(--status-warning)" aria-hidden="true" />
            <span className="pending-approvals-title">
              Orders requiring human authorization ({pendingApprovals.length})
            </span>
          </div>
          <div className="pending-approvals-list">
            {pendingApprovals.map((req) => (
              <div key={req.id} className="pending-approval-row">
                <div className="pending-approval-info">
                  <span className="font-semibold text-primary">{req.product_id}</span>
                  <span className="text-secondary">&bull; {req.merchant_domain} &bull;</span>
                  <span className="font-mono tabular-nums text-primary font-medium">
                    ${Number(req.subtotal).toFixed(2)} {req.currency}
                  </span>
                  <div className="pending-reason">
                    Reason: {req.escalation_reason || 'Subtotal exceeds threshold'}
                  </div>
                </div>
                <div className="pending-approval-actions">
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    disabled={resolvingId === req.id}
                    onClick={() => handleResolvePending(req.id, 'APPROVE')}
                  >
                    {resolvingId === req.id ? 'Processing…' : 'Approve'}
                  </button>
                  <button
                    type="button"
                    className="btn btn-destructive-outline btn-sm"
                    disabled={resolvingId === req.id}
                    onClick={() => handleResolvePending(req.id, 'DENY')}
                  >
                    Deny
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 2. Main Ledger Panel */}
      <div className="panel ledger-table-panel">
        {/* Toolbar Row */}
        <div className="ledger-toolbar">
          <div className="ledger-toolbar-left">
            <input
              type="text"
              placeholder="Filter ledger by item, merchant, or hash…"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="search-input"
              aria-label="Filter ledger entries"
            />
            <div className="segmented-control" role="tablist" aria-label="Filter status">
              {['ALL', 'BLOCKED', 'CAPTURED', 'PENDING'].map((st) => (
                <button
                  key={st}
                  type="button"
                  role="tab"
                  aria-selected={filterStatus === st}
                  className={`segmented-button ${filterStatus === st ? 'active' : ''}`}
                  onClick={() => setFilterStatus(st)}
                >
                  {st.charAt(0) + st.slice(1).toLowerCase()}
                </button>
              ))}
            </div>
          </div>

          <div className="ledger-toolbar-right">
            {/* Plain-text chain status with icon */}
            <div className="chain-status-text">
              {chainVerification ? (
                chainVerification.valid ? (
                  <span className="chain-valid">
                    <CheckCircle2 size={16} color="var(--status-success)" aria-hidden="true" />
                    <span>Chain valid</span>
                  </span>
                ) : (
                  <span className="chain-broken">
                    <XCircle size={16} color="var(--status-danger)" aria-hidden="true" />
                    <span>Chain broken</span>
                  </span>
                )
              ) : (
                <span className="chain-unverified">
                  <Clock size={16} color="var(--text-secondary)" aria-hidden="true" />
                  <span>Not verified</span>
                </span>
              )}
            </div>

            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={handleVerifyChain}
              disabled={verifying}
            >
              {verifying ? 'Verifying…' : 'Verify chain'}
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={handleExportAudit}
            >
              Export signed JSON
            </button>
          </div>
        </div>

        {/* 3. AG Grid or Empty State */}
        {attempts.length === 0 ? (
          <div className="empty-ledger-state">
            <p className="empty-ledger-text">No verification attempts recorded in this session yet.</p>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => onSwitchTab && onSwitchTab('console')}
            >
              Run a scenario
            </button>
          </div>
        ) : (
          <div className="ag-theme-quartz ledger-grid-container">
            <AgGridReact
              theme={gridTheme}
              rowData={rowData}
              columnDefs={columnDefs}
              defaultColDef={defaultColDef}
              rowHeight={44}
              headerHeight={38}
              suppressCellFocus={true}
              pagination={true}
              paginationPageSize={10}
              paginationPageSizeSelector={[10, 20, 50]}
              onRowClicked={(e) => setSelectedAttempt(e.data)}
            />
          </div>
        )}
      </div>

      {/* 4. Attempt Inspector: 480px Wide Right-Side Drawer (No inner cards) */}
      {selectedAttempt && (
        <div className="drawer-overlay" onClick={() => setSelectedAttempt(null)}>
          <div
            className="attempt-drawer"
            role="dialog"
            aria-label="Attempt inspector"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Drawer Header */}
            <div className="drawer-header">
              <div className="drawer-header-titles">
                <span className="drawer-kicker">Audit ledger inspector</span>
                <h3 className="drawer-title">
                  Attempt <span className="font-mono">{selectedAttempt.attempt_id}</span>
                </h3>
              </div>
              <button
                type="button"
                className="btn-icon-subtle"
                onClick={() => setSelectedAttempt(null)}
                aria-label="Close attempt inspector"
              >
                <X size={16} />
              </button>
            </div>

            {/* Section 1: Summary */}
            <div className="drawer-section">
              <div className="drawer-section-title">Summary</div>
              <div className="drawer-kv-grid">
                <div className="drawer-kv-item">
                  <span className="drawer-kv-label">Status</span>
                  <div className="drawer-kv-value">
                    {selectedAttempt.status === 'BLOCKED' ? (
                      <span className="status-tag status-tag-danger">
                        <XCircle size={12} aria-hidden="true" />
                        <span>Blocked</span>
                      </span>
                    ) : selectedAttempt.status === 'PENDING' || selectedAttempt.needs_human_approval ? (
                      <span className="status-tag status-tag-warning">
                        <Clock size={12} aria-hidden="true" />
                        <span>Pending approval</span>
                      </span>
                    ) : (
                      <span className="status-tag status-tag-success">
                        <CheckCircle2 size={12} aria-hidden="true" />
                        <span>Captured</span>
                      </span>
                    )}
                  </div>
                </div>
                <div className="drawer-kv-item">
                  <span className="drawer-kv-label">Timestamp</span>
                  <span className="drawer-kv-value font-mono tabular-nums">{selectedAttempt.timestamp}</span>
                </div>
                <div className="drawer-kv-item">
                  <span className="drawer-kv-label">Merchant</span>
                  <span className="drawer-kv-value">{selectedAttempt.merchant_domain}</span>
                </div>
                <div className="drawer-kv-item">
                  <span className="drawer-kv-label">Subtotal</span>
                  <span className="drawer-kv-value font-mono tabular-nums font-semibold">
                    ${Number(selectedAttempt.computed_subtotal || selectedAttempt.unit_price || 0).toFixed(2)} USD
                  </span>
                </div>
              </div>
            </div>

            {/* Section 2: Agent request */}
            <div className="drawer-section">
              <div className="drawer-section-title">Agent request</div>
              <div className="drawer-kv-grid">
                <div className="drawer-kv-item">
                  <span className="drawer-kv-label">Product ID</span>
                  <span className="drawer-kv-value font-mono">{selectedAttempt.product_id}</span>
                </div>
                <div className="drawer-kv-item">
                  <span className="drawer-kv-label">Quantity</span>
                  <span className="drawer-kv-value font-mono tabular-nums">{selectedAttempt.quantity || 1}</span>
                </div>
                <div className="drawer-kv-item">
                  <span className="drawer-kv-label">Requested price</span>
                  <span className="drawer-kv-value font-mono tabular-nums">
                    ${Number(selectedAttempt.unit_price || 0).toFixed(2)}
                  </span>
                </div>
                <div className="drawer-kv-item">
                  <span className="drawer-kv-label">Policy bound</span>
                  <span className="drawer-kv-value font-mono">{selectedAttempt.policy_id || 'policy_enterprise_standard'}</span>
                </div>
              </div>
              {selectedAttempt.agent_reasoning && (
                <div className="drawer-reasoning-row">
                  <span className="drawer-kv-label">Agent reasoning</span>
                  <p className="drawer-reasoning-text">{selectedAttempt.agent_reasoning}</p>
                </div>
              )}
            </div>

            {/* Section 3: Catalog ground truth */}
            <div className="drawer-section">
              <div className="drawer-section-title">Catalog ground truth</div>
              <div className="drawer-kv-grid">
                <div className="drawer-kv-item full-width">
                  <span className="drawer-kv-label">Canonical item title</span>
                  <span className="drawer-kv-value">{selectedAttempt.product_title || 'Catalog item verified'}</span>
                </div>
                <div className="drawer-kv-item">
                  <span className="drawer-kv-label">Catalog unit price</span>
                  <span className="drawer-kv-value font-mono tabular-nums">
                    ${Number(selectedAttempt.unit_price || selectedAttempt.computed_subtotal || 0).toFixed(2)}
                  </span>
                </div>
                <div className="drawer-kv-item">
                  <span className="drawer-kv-label">Authorized seller</span>
                  <span className="drawer-kv-value">{selectedAttempt.merchant_domain}</span>
                </div>
              </div>
            </div>

            {/* Section 4: Rule results */}
            <div className="drawer-section">
              <div className="drawer-section-title">Rule results</div>
              <div className="drawer-rules-list">
                {/* Rule 1 */}
                <div className="drawer-rule-item">
                  <div className="drawer-rule-header">
                    <span className="drawer-rule-name">1. Domain allowlist</span>
                    {selectedAttempt.violations?.some((v) => v.rule?.includes('1') || v.rule?.toLowerCase().includes('domain')) ? (
                      <span className="status-tag status-tag-danger">Fail</span>
                    ) : (
                      <span className="status-tag status-tag-success">Pass</span>
                    )}
                  </div>
                  <div className="drawer-rule-detail">Merchant domain verified against mandate authorized merchant list.</div>
                </div>

                {/* Rule 2 */}
                <div className="drawer-rule-item">
                  <div className="drawer-rule-header">
                    <span className="drawer-rule-name">2. SKU &amp; price integrity</span>
                    {selectedAttempt.violations?.some((v) => v.rule?.includes('2') || v.rule?.toLowerCase().includes('spec') || v.rule?.toLowerCase().includes('price')) ? (
                      <span className="status-tag status-tag-danger">Fail</span>
                    ) : (
                      <span className="status-tag status-tag-success">Pass</span>
                    )}
                  </div>
                  <div className="drawer-rule-detail">Catalog price match and hardware specification ground truth check.</div>
                </div>

                {/* Rule 3 */}
                <div className="drawer-rule-item">
                  <div className="drawer-rule-header">
                    <span className="drawer-rule-name">3. Spending limit &amp; velocity</span>
                    {selectedAttempt.violations?.some((v) => v.rule?.includes('3') || v.rule?.toLowerCase().includes('budget') || v.rule?.toLowerCase().includes('velocity') || v.rule?.toLowerCase().includes('limit')) ? (
                      <span className="status-tag status-tag-danger">Fail</span>
                    ) : (
                      <span className="status-tag status-tag-success">Pass</span>
                    )}
                  </div>
                  <div className="drawer-rule-detail">Quantity caps, per-order limits, and rate limit velocity windows.</div>
                </div>

                {/* Rule 4 */}
                <div className="drawer-rule-item">
                  <div className="drawer-rule-header">
                    <span className="drawer-rule-name">4. Supervisor escalation</span>
                    {selectedAttempt.needs_human_approval || selectedAttempt.status === 'PENDING_APPROVAL' ? (
                      <span className="status-tag status-tag-warning">Held</span>
                    ) : (
                      <span className="status-tag status-tag-success">Pass</span>
                    )}
                  </div>
                  <div className="drawer-rule-detail">High-value transactions escalate to supervisor HMAC approval token.</div>
                </div>
              </div>
            </div>

            {/* Section 5: Settlement */}
            <div className="drawer-section">
              <div className="drawer-section-title">Settlement</div>
              <div className="drawer-kv-grid">
                <div className="drawer-kv-item">
                  <span className="drawer-kv-label">PayPal order ID</span>
                  <span className="drawer-kv-value font-mono">
                    {selectedAttempt.paypal_order_id || '—'}
                  </span>
                </div>
                <div className="drawer-kv-item">
                  <span className="drawer-kv-label">PayPal capture ID</span>
                  <span className="drawer-kv-value font-mono">
                    {selectedAttempt.paypal_capture_id || '—'}
                  </span>
                </div>
                <div className="drawer-kv-item full-width">
                  <span className="drawer-kv-label">Settlement outcome</span>
                  <span className="drawer-kv-value">
                    {selectedAttempt.status === 'CAPTURED'
                      ? 'Authorized and captured on PayPal Sandbox.'
                      : selectedAttempt.status === 'BLOCKED'
                      ? 'No settlement initiated. Order construction rejected pre-call.'
                      : selectedAttempt.status === 'REFUNDED'
                      ? 'Captured funds refunded via PayPal Sandbox API.'
                      : 'Pending supervisor decision.'}
                  </span>
                </div>
              </div>
            </div>

            {/* Section 6: Audit hash */}
            <div className="drawer-section">
              <div className="drawer-section-title">Audit hash</div>
              {selectedAttempt.audit_event_hash ? (
                <div className="drawer-hash-block">
                  <div className="drawer-hash-row">
                    <code className="drawer-hash-code font-mono">
                      {selectedAttempt.audit_event_hash}
                    </code>
                    <button
                      type="button"
                      className="btn-icon-subtle"
                      title="Copy full cryptographic hash"
                      onClick={() => {
                        if (navigator.clipboard) {
                          navigator.clipboard.writeText(selectedAttempt.audit_event_hash)
                          setCopiedFullHash(true)
                          setTimeout(() => setCopiedFullHash(false), 2000)
                        }
                      }}
                    >
                      {copiedFullHash ? <Check size={14} color="var(--status-success)" /> : <Copy size={14} />}
                    </button>
                  </div>
                  <div className="drawer-hash-meta">
                    SHA-256 block hash linked to cryptographic audit event chain.
                  </div>
                </div>
              ) : (
                <div className="text-secondary text-xs">No cryptographic hash emitted for this attempt.</div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
