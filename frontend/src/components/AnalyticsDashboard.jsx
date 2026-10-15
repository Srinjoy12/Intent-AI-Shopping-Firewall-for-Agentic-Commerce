import React, { useState, useMemo } from 'react'
import { AgGridReact } from 'ag-grid-react'
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community'
import 'ag-grid-community/styles/ag-grid.css'
import 'ag-grid-community/styles/ag-theme-quartz.css'
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
  DollarSign,
  Eye,
  X,
  Lock,
  ExternalLink,
  Bot,
  ShoppingCart,
} from 'lucide-react'

// Register AG Grid Community modules
ModuleRegistry.registerModules([AllCommunityModule])

// Custom dark Quartz theme matching Intent design tokens
const darkQuartzTheme = themeQuartz.withParams({
  backgroundColor: '#0c121e',
  headerBackgroundColor: '#0f172a',
  headerTextColor: '#94a3b8',
  foregroundColor: '#f1f5f9',
  borderColor: '#1e293b',
  rowHoverColor: 'rgba(30, 41, 59, 0.6)',
  selectedRowBackgroundColor: 'rgba(30, 58, 138, 0.25)',
  fontFamily: 'Inter, system-ui, sans-serif',
  fontSize: 12,
})

export default function AnalyticsDashboard({ analytics, attempts, onRefresh }) {
  const [filterStatus, setFilterStatus] = useState('ALL')
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedAttempt, setSelectedAttempt] = useState(null)

  const summary = analytics?.summary || {
    total_attempts: 0,
    blocked_count: 0,
    verified_count: 0,
    captured_count: 0,
    refunded_count: 0,
    dollars_prevented: 0,
    dollars_captured: 0,
    violation_breakdown: {},
  }

  // Format timestamp helper
  const formatTime = (isoString) => {
    if (!isoString) return '-'
    try {
      const d = new Date(isoString)
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    } catch {
      return isoString.slice(11, 19)
    }
  }

  // Filter attempts for AG Grid rowData
  const rowData = useMemo(() => {
    return (attempts || []).filter((att) => {
      const matchesStatus = filterStatus === 'ALL' || att.status === filterStatus
      const term = searchTerm.toLowerCase().trim()
      const matchesSearch =
        !term ||
        att.attempt_id?.toLowerCase().includes(term) ||
        att.product_id?.toLowerCase().includes(term) ||
        att.product_title?.toLowerCase().includes(term) ||
        att.merchant_domain?.toLowerCase().includes(term) ||
        att.paypal_order_id?.toLowerCase().includes(term)
      return matchesStatus && matchesSearch
    })
  }, [attempts, filterStatus, searchTerm])

  // Column definitions for AG Grid
  const columnDefs = useMemo(
    () => [
      {
        field: 'timestamp',
        headerName: 'TIME',
        width: 110,
        valueFormatter: (p) => formatTime(p.value),
        cellClass: 'font-mono text-xs text-slate-400',
        sort: 'desc',
      },
      {
        field: 'attempt_id',
        headerName: 'ATTEMPT ID',
        width: 140,
        cellRenderer: (p) => (
          <span
            className="font-mono text-xs font-semibold text-sky-400 hover:text-sky-300 underline cursor-pointer"
            onClick={() => setSelectedAttempt(p.data)}
            title="Click to inspect LLM intent vs Ground Truth"
          >
            {p.value}
          </span>
        ),
      },
      {
        field: 'product_id',
        headerName: 'PRODUCT / SKU',
        flex: 1.4,
        minWidth: 200,
        cellRenderer: (p) => (
          <div className="flex flex-col leading-tight py-1">
            <span className="font-mono text-xs text-amber-400 font-semibold">{p.value}</span>
            <span className="text-xs text-slate-300 truncate" title={p.data.product_title}>
              {p.data.product_title || 'Catalog item'}
            </span>
          </div>
        ),
      },
      {
        field: 'merchant_domain',
        headerName: 'RETAILER',
        width: 135,
        cellRenderer: (p) => (
          <span className="font-mono text-xs text-slate-300 bg-slate-800/80 px-2 py-0.5 rounded border border-slate-700">
            {p.value}
          </span>
        ),
      },
      {
        field: 'quantity',
        headerName: 'QTY',
        width: 75,
        cellClass: 'font-mono text-xs text-center font-bold text-slate-200',
      },
      {
        field: 'computed_subtotal',
        headerName: 'SUBTOTAL',
        width: 115,
        cellRenderer: (p) => (
          <span className="font-mono text-xs font-bold text-slate-100">
            ${p.value || p.data.unit_price || '0.00'}
          </span>
        ),
      },
      {
        field: 'status',
        headerName: 'GATEWAY STATUS',
        width: 180,
        cellRenderer: (p) => {
          const st = p.value
          if (st === 'BLOCKED') {
            return (
              <span className="inline-flex items-center gap-1 font-mono text-[11px] font-bold px-2.5 py-0.5 rounded-full bg-red-950/80 text-rose-300 border border-red-800/80">
                <span className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse"></span>
                BLOCKED
              </span>
            )
          }
          if (st === 'CAPTURED') {
            return (
              <span className="inline-flex items-center gap-1 font-mono text-[11px] font-bold px-2.5 py-0.5 rounded-full bg-emerald-950/80 text-emerald-300 border border-emerald-800/80">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                CAPTURED
              </span>
            )
          }
          if (st === 'REFUNDED') {
            return (
              <span className="inline-flex items-center gap-1 font-mono text-[11px] font-bold px-2.5 py-0.5 rounded-full bg-purple-950/80 text-purple-300 border border-purple-800/80">
                REFUNDED
              </span>
            )
          }
          return (
            <span className="inline-flex items-center gap-1 font-mono text-[11px] font-bold px-2.5 py-0.5 rounded-full bg-sky-950/80 text-sky-300 border border-sky-800/80">
              READY FOR PAYPAL
            </span>
          )
        },
      },
      {
        field: 'violations',
        headerName: 'THREAT AUDIT / VIOLATIONS',
        flex: 1.5,
        minWidth: 210,
        cellRenderer: (p) => {
          const viols = p.value || []
          if (viols.length === 0) {
            return <span className="font-mono text-xs text-emerald-400">✓ 0 Violations (Clean)</span>
          }
          return (
            <div className="flex flex-wrap gap-1 items-center py-1">
              {viols.map((v, i) => (
                <span
                  key={i}
                  className="font-mono text-[10px] bg-red-900/60 text-rose-200 border border-red-700/60 px-1.5 py-0.5 rounded"
                  title={v.detail}
                >
                  {v.rule}
                </span>
              ))}
            </div>
          )
        },
      },
      {
        field: 'paypal_order_id',
        headerName: 'PAYPAL ORDER ID',
        width: 175,
        cellRenderer: (p) => {
          if (!p.value) return <span className="text-slate-600 font-mono text-xs">-</span>
          return (
            <span className="font-mono text-xs text-sky-300 hover:text-sky-200 underline">
              {p.value}
            </span>
          )
        },
      },
      {
        headerName: 'ACTIONS',
        width: 100,
        sortable: false,
        filter: false,
        cellRenderer: (p) => (
          <button
            type="button"
            className="flex items-center gap-1 font-mono text-[11px] bg-slate-800 hover:bg-slate-700 text-sky-300 border border-slate-700 px-2 py-1 rounded"
            onClick={() => setSelectedAttempt(p.data)}
          >
            <Eye size={12} />
            <span>Inspect</span>
          </button>
        ),
      },
    ],
    []
  )

  const defaultColDef = useMemo(
    () => ({
      sortable: true,
      filter: true,
      resizable: true,
    }),
    []
  )

  return (
    <div className="analytics-dashboard-container">
      {/* Header */}
      <div className="analytics-header">
        <div className="analytics-header-left">
          <Layers size={18} className="analytics-icon text-sky-400" />
          <div>
            <div className="flex items-center gap-2">
              <h2 className="analytics-title">AG STUDIO // GATEWAY ANALYTICS & THREAT AUDIT</h2>
              <span className="font-mono text-[10px] px-2 py-0.5 bg-sky-950 text-sky-300 border border-sky-800 rounded">
                POWERED BY AG GRID &bull; v36
              </span>
            </div>
            <p className="analytics-subtitle">
              Real-time audit log of deterministic firewall decisions and PayPal Sandbox settlements.
            </p>
          </div>
        </div>

        <button type="button" className="btn-refresh-analytics" onClick={onRefresh}>
          <RotateCcw size={14} />
          <span>Refresh Data</span>
        </button>
      </div>

      {/* 5 KPI Metric Cards (Including Claude's Recommended $ Overspend Prevented) */}
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

        {/* CFO Metric: Total Dollars Protected */}
        <div className="kpi-card warning">
          <span className="kpi-label">$ OVERSPEND PREVENTED</span>
          <div className="kpi-val-row">
            <DollarSign size={20} className="text-amber-400" />
            <span className="kpi-val text-amber-400 font-mono">
              ${Number(summary.dollars_prevented || 0).toFixed(2)}
            </span>
          </div>
          <span className="kpi-sub">Halted Before PayPal Funds Moved</span>
        </div>

        {/* Revenue Metric: Safely Captured */}
        <div className="kpi-card success">
          <span className="kpi-label">$ SAFELY CAPTURED</span>
          <div className="kpi-val-row">
            <CheckCircle size={20} className="text-success" />
            <span className="kpi-val text-success font-mono">
              ${Number(summary.dollars_captured || 0).toFixed(2)}
            </span>
          </div>
          <span className="kpi-sub">PayPal Sandbox Captured Funds</span>
        </div>

        <div className="kpi-card accent">
          <span className="kpi-label">DEFENSE POLICY</span>
          <div className="kpi-val-row">
            <ShieldCheck size={20} className="text-accent" />
            <span className="kpi-val text-accent font-mono text-lg">pol_demo_01</span>
          </div>
          <span className="kpi-sub">Auto &le; $1,000 &bull; Cap $1,200</span>
        </div>
      </div>

      {/* Rule Violation Breakdown */}
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

      {/* Genuine AG Grid Component with Dark Quartz Theme */}
      <div className="ag-grid-wrapper">
        <div className="table-controls-bar">
          <div className="table-search">
            <Search size={14} className="search-icon" />
            <input
              type="text"
              placeholder="Search by attempt ID, SKU, domain, PayPal ID..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="search-input"
            />
          </div>

          <div className="table-filters">
            <Filter size={14} className="filter-icon" />
            <div className="filter-buttons">
              {['ALL', 'BLOCKED', 'VERIFIED_READY_FOR_PAYPAL', 'CAPTURED', 'REFUNDED'].map((st) => (
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

        {/* AG Grid React Table */}
        <div className="ag-theme-quartz-dark" style={{ height: '420px', width: '100%' }}>
          <AgGridReact
            theme={darkQuartzTheme}
            rowData={rowData}
            columnDefs={columnDefs}
            defaultColDef={defaultColDef}
            rowSelection="single"
            pagination={true}
            paginationPageSize={10}
            paginationPageSizeSelector={[10, 20, 50]}
            onRowClicked={(e) => setSelectedAttempt(e.data)}
            overlayNoRowsTemplate="<span class='font-mono text-slate-400 p-4'>No matching gateway attempts found. Run an attack preset above to record an audit trace.</span>"
          />
        </div>
      </div>

      {/* Master-Detail Row Inspector Drawer (Claude Q2 Recommendation) */}
      {selectedAttempt && (
        <div className="audit-detail-drawer">
          <div className="audit-detail-header">
            <div className="audit-detail-title">
              <Database size={16} className="text-sky-400" />
              <span>Master-Detail Audit Inspector: Attempt #{selectedAttempt.attempt_id}</span>
              <span className={`status-chip font-mono text-[10px] ${
                selectedAttempt.status === 'BLOCKED'
                  ? 'chip-blocked'
                  : selectedAttempt.status === 'CAPTURED'
                  ? 'chip-captured'
                  : 'chip-verified'
              }`}>
                {selectedAttempt.status}
              </span>
            </div>
            <button
              type="button"
              className="btn-close-detail"
              onClick={() => setSelectedAttempt(null)}
              title="Close drawer"
            >
              <X size={16} />
            </button>
          </div>

          <div className="audit-detail-cols">
            {/* Col 1: Untrusted LLM Intent */}
            <div className="audit-col-card red-border">
              <div className="audit-col-title">
                <Bot size={14} className="text-rose-400" />
                <span>1. UNTRUSTED LLM INTENT</span>
              </div>
              <div className="audit-kv-row">
                <span className="audit-k">SUBMITTED PRODUCT ID:</span>
                <span className="audit-v text-rose-300 font-bold">{selectedAttempt.product_id}</span>
              </div>
              <div className="audit-kv-row">
                <span className="audit-k">REQUESTED DOMAIN:</span>
                <span className="audit-v">{selectedAttempt.merchant_domain}</span>
              </div>
              <div className="audit-kv-row">
                <span className="audit-k">SUBMITTED QUANTITY:</span>
                <span className="audit-v">{selectedAttempt.quantity} unit(s)</span>
              </div>
              <div className="audit-kv-row">
                <span className="audit-k">LLM AGENT REASONING:</span>
                <div className="audit-reasoning-box font-mono">
                  {selectedAttempt.agent_reasoning || 'No raw reasoning logged.'}
                </div>
              </div>
            </div>

            {/* Col 2: Authoritative Channel3 Ground Truth */}
            <div className="audit-col-card blue-border">
              <div className="audit-col-title">
                <ShoppingCart size={14} className="text-sky-400" />
                <span>2. CHANNEL3 CATALOG GROUND TRUTH</span>
              </div>
              <div className="audit-kv-row">
                <span className="audit-k">CANONICAL TITLE:</span>
                <span className="audit-v text-slate-100">{selectedAttempt.product_title || 'N/A'}</span>
              </div>
              <div className="audit-kv-row">
                <span className="audit-k">AUTHORITATIVE UNIT PRICE:</span>
                <span className="audit-v text-emerald-400 font-bold">
                  ${selectedAttempt.unit_price || '0.00'} USD
                </span>
              </div>
              <div className="audit-kv-row">
                <span className="audit-k">COMPUTED SUBTOTAL:</span>
                <span className="audit-v font-bold">${selectedAttempt.computed_subtotal || '0.00'} USD</span>
              </div>
              <div className="audit-kv-row">
                <span className="audit-k">GATEWAY DATA SOURCE:</span>
                <span className="audit-v text-sky-300">
                  {selectedAttempt.product_id?.startsWith('fixture_')
                    ? 'Gateway Fixture Cache (0 API credits burned)'
                    : 'Channel3 Live v1 Catalog API'}
                </span>
              </div>
            </div>

            {/* Col 3: Gateway Verdict & PayPal Settlement */}
            <div className="audit-col-card green-border">
              <div className="audit-col-title">
                <Lock size={14} className="text-emerald-400" />
                <span>3. GATEWAY VERDICT & PAYPAL SETTLEMENT</span>
              </div>
              <div className="audit-kv-row">
                <span className="audit-k">POLICY ENFORCED:</span>
                <span className="audit-v text-sky-400">{selectedAttempt.policy_id}</span>
              </div>
              <div className="audit-kv-row">
                <span className="audit-k">VIOLATIONS DETECTED:</span>
                {selectedAttempt.violations && selectedAttempt.violations.length > 0 ? (
                  <div className="flex flex-col gap-1 mt-1">
                    {selectedAttempt.violations.map((v, i) => (
                      <div key={i} className="text-[11px] bg-red-950/70 border border-red-800 text-rose-300 p-1.5 rounded font-mono">
                        <strong>[{v.rule}]:</strong> {v.detail}
                      </div>
                    ))}
                  </div>
                ) : (
                  <span className="audit-v text-emerald-400 font-bold">Passed all 4 Deterministic Rules</span>
                )}
              </div>
              {selectedAttempt.remediation && (
                <div className="audit-kv-row">
                  <span className="audit-k">DETERMINISTIC REMEDIATION JSON:</span>
                  <div className="audit-reasoning-box bg-slate-900 border-amber-600/50 text-amber-300 font-mono text-[11px]">
                    <div><strong>ACTION:</strong> {selectedAttempt.remediation.action}</div>
                    <div><strong>ADVICE:</strong> {selectedAttempt.remediation.instruction}</div>
                  </div>
                </div>
              )}
              <div className="audit-kv-row mt-2">
                <span className="audit-k">PAYPAL SANDBOX SETTLEMENT:</span>
                {selectedAttempt.paypal_order_id ? (
                  <div className="font-mono text-xs text-slate-200 mt-1 space-y-1">
                    <div>Order ID: <span className="text-sky-400 font-bold">{selectedAttempt.paypal_order_id}</span></div>
                    {selectedAttempt.paypal_capture_id && (
                      <div>Capture ID: <span className="text-emerald-400 font-bold">{selectedAttempt.paypal_capture_id}</span></div>
                    )}
                  </div>
                ) : (
                  <span className="audit-v text-rose-400 font-bold">Halted (0 Funds Moved)</span>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
