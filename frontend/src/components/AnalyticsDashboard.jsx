import React, { useState, useMemo } from 'react'
import { AgGridReact } from 'ag-grid-react'
import { AgCharts } from 'ag-charts-react'
import { ModuleRegistry, AllCommunityModule, themeQuartz } from 'ag-grid-community'
import {
  ModuleRegistry as ChartModuleRegistry,
  AllCommunityModule as AllChartsCommunityModule,
} from 'ag-charts-community'
import 'ag-grid-community/styles/ag-grid.css'
import 'ag-grid-community/styles/ag-theme-quartz.css'
import {
  BarChart3,
  ShieldAlert,
  ShieldCheck,
  CheckCircle2,
  RotateCcw,
  Search,
  Filter,
  Layers,
  Database,
  DollarSign,
  Eye,
  X,
  Lock,
  Bot,
  ShoppingCart,
} from 'lucide-react'

// Register AG Grid Community modules
ModuleRegistry.registerModules([AllCommunityModule])

// Register AG Charts Community modules
ChartModuleRegistry.registerModules([AllChartsCommunityModule])

// Custom PayPal Light Quartz theme matching official PayPal design tokens
const paypalQuartzTheme = themeQuartz.withParams({
  backgroundColor: '#FFFFFF',
  headerBackgroundColor: '#F8FAFC',
  headerTextColor: '#001C3F',
  foregroundColor: '#001C3F',
  borderColor: '#E2E8F0',
  rowHoverColor: '#F8FAFC',
  selectedRowBackgroundColor: '#EBF5FF',
  fontFamily: 'Inter, system-ui, sans-serif',
  fontSize: 13,
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

  // Humanize rule violation handles
  const humanizeRule = (ruleKey) => {
    const map = {
      STRUCTURED_ATTRIBUTE_MISMATCH: 'RAM / Spec Mismatch (Rule 2)',
      OFFER_UNAVAILABLE: 'Offer / Stock Unavailable (Rule 1)',
      BUDGET_EXCEEDED: 'Budget Limit Exceeded (Rule 3)',
      MAX_QUANTITY_EXCEEDED: 'Quantity Limit Exceeded (Rule 3)',
      UNVERIFIABLE_ATTRIBUTE: 'Unverifiable Attribute (Rule 2)',
    }
    return map[ruleKey] || ruleKey.replace(/_/g, ' ')
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
        headerName: 'Time',
        width: 120,
        valueFormatter: (p) => formatTime(p.value),
        cellClass: 'text-xs text-slate-500 font-mono',
        sort: 'desc',
      },
      {
        field: 'attempt_id',
        headerName: 'Attempt ID',
        width: 140,
        cellRenderer: (p) => (
          <span
            className="text-xs font-semibold text-[#0070BA] hover:underline cursor-pointer font-mono"
            onClick={() => setSelectedAttempt(p.data)}
            title="Inspect comparative truth audit"
          >
            {p.value}
          </span>
        ),
      },
      {
        field: 'product_title',
        headerName: 'Product & SKU',
        flex: 1.6,
        minWidth: 240,
        cellRenderer: (p) => (
          <div className="flex flex-col leading-tight py-1">
            <span className="text-xs text-slate-900 font-semibold truncate">
              {p.value || p.data.product_id || 'Catalog item'}
            </span>
            <span className="text-[11px] text-slate-400 font-mono">
              SKU: {p.data.product_id}
            </span>
          </div>
        ),
      },
      {
        field: 'merchant_domain',
        headerName: 'Merchant',
        width: 140,
        cellRenderer: (p) => (
          <span className="text-xs text-slate-700 bg-slate-100 px-2 py-0.5 rounded border border-slate-200">
            {p.value}
          </span>
        ),
      },
      {
        field: 'quantity',
        headerName: 'Qty',
        width: 75,
        cellClass: 'text-xs text-center font-bold text-slate-700 font-mono',
      },
      {
        field: 'computed_subtotal',
        headerName: 'Subtotal',
        width: 125,
        cellRenderer: (p) => (
          <span className="text-xs font-bold text-slate-900 font-mono">
            ${Number(p.value || p.data.unit_price || 0).toFixed(2)}
          </span>
        ),
      },
      {
        field: 'status',
        headerName: 'Gateway Decision',
        width: 185,
        cellRenderer: (p) => {
          const st = p.value
          if (st === 'BLOCKED') {
            return (
              <span className="inline-flex items-center gap-1.5 text-[11px] font-bold px-2.5 py-0.5 rounded-full bg-red-50 text-red-700 border border-red-200">
                <span className="w-1.5 h-1.5 rounded-full bg-red-600"></span>
                BLOCKED
              </span>
            )
          }
          if (st === 'CAPTURED') {
            return (
              <span className="inline-flex items-center gap-1.5 text-[11px] font-bold px-2.5 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-600"></span>
                CAPTURED
              </span>
            )
          }
          if (st === 'REFUNDED') {
            return (
              <span className="inline-flex items-center gap-1.5 text-[11px] font-bold px-2.5 py-0.5 rounded-full bg-purple-50 text-purple-700 border border-purple-200">
                REFUNDED
              </span>
            )
          }
          return (
            <span className="inline-flex items-center gap-1.5 text-[11px] font-bold px-2.5 py-0.5 rounded-full bg-blue-50 text-[#0070BA] border border-blue-200">
              READY FOR PAYPAL
            </span>
          )
        },
      },
      {
        field: 'violations',
        headerName: 'Security Verdict',
        flex: 1.4,
        minWidth: 220,
        cellRenderer: (p) => {
          const viols = p.value || []
          if (viols.length === 0) {
            return <span className="text-xs text-emerald-700 font-medium">✓ Clean (Zero Violations)</span>
          }
          return (
            <div className="flex flex-wrap gap-1 items-center py-1">
              {viols.map((v, i) => (
                <span
                  key={i}
                  className="text-[10px] bg-red-50 text-red-700 border border-red-200 px-1.5 py-0.5 rounded font-medium"
                  title={v.detail}
                >
                  {humanizeRule(v.rule)}
                </span>
              ))}
            </div>
          )
        },
      },
      {
        field: 'paypal_order_id',
        headerName: 'PayPal Order ID',
        width: 185,
        cellRenderer: (p) => {
          if (!p.value) return <span className="text-slate-400 font-mono text-xs">-</span>
          return (
            <span className="text-xs text-[#0070BA] font-mono hover:underline">
              {p.value}
            </span>
          )
        },
      },
      {
        headerName: 'Action',
        width: 100,
        sortable: false,
        filter: false,
        cellRenderer: (p) => (
          <button
            type="button"
            className="btn-grid-inspect"
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

  // Prepare data for AG Charts visualization
  const chartData = useMemo(() => {
    const list = []
    if (summary.captured_count > 0) {
      list.push({ category: 'Captured', count: summary.captured_count })
    }
    if (summary.verified_count > 0) {
      list.push({ category: 'Human Review', count: summary.verified_count })
    }
    const breakdown = summary.violation_breakdown || {}
    Object.entries(breakdown).forEach(([k, count]) => {
      const shortName = humanizeRule(k).split(' (')[0]
      list.push({ category: shortName, count })
    })
    if (list.length === 0) {
      list.push({ category: 'Standby', count: 1 })
    }
    return list
  }, [summary])

  const chartOptions = useMemo(
    () => ({
      data: chartData,
      title: {
        text: 'Threat & Settlement Distribution',
        fontSize: 12,
        fontFamily: 'Inter, system-ui, sans-serif',
        color: '#0F172A',
      },
      series: [
        {
          type: 'donut',
          calloutLabelKey: 'category',
          angleKey: 'count',
          innerRadiusRatio: 0.62,
          fills: ['#10B981', '#0070E0', '#EF4444', '#F59E0B', '#8B5CF6'],
        },
      ],
      legend: {
        position: 'right',
        item: {
          label: {
            fontSize: 11,
            fontFamily: 'Inter, system-ui, sans-serif',
            color: '#475569',
          },
        },
      },
      background: {
        fill: 'transparent',
      },
    }),
    [chartData]
  )

  return (
    <div className="analytics-dashboard-container">
      {/* Header */}
      <div className="analytics-header">
        <div className="analytics-header-left">
          <div className="analytics-icon-badge">
            <Layers size={18} className="text-paypal-blue" />
          </div>
          <div>
            <div className="analytics-title-row">
              <h2 className="analytics-title">Gateway Audit Log &amp; Security Analytics</h2>
              <span className="brand-badge">AG Grid v36 &amp; AG Charts</span>
            </div>
            <p className="analytics-subtitle">
              Deterministic firewall decision history and real-time PayPal Sandbox transaction settlement ledger.
            </p>
          </div>
        </div>

        <button type="button" className="btn-refresh-analytics" onClick={onRefresh}>
          <RotateCcw size={13} />
          <span>Refresh Ledger</span>
        </button>
      </div>

      {/* 5 KPI Metric Cards */}
      <div className="kpi-grid">
        <div className="kpi-card">
          <span className="kpi-label">Total Attempts</span>
          <div className="kpi-val-row">
            <span className="kpi-val">{summary.total_attempts}</span>
          </div>
          <span className="kpi-sub">Firewall Interceptions</span>
        </div>

        <div className="kpi-card danger">
          <span className="kpi-label">Blocked Threats</span>
          <div className="kpi-val-row">
            <ShieldAlert size={18} className="text-danger" />
            <span className="kpi-val text-danger">{summary.blocked_count}</span>
          </div>
          <span className="kpi-sub">Fail-Closed Interceptions</span>
        </div>

        {/* Dollars Prevented */}
        <div className="kpi-card warning">
          <span className="kpi-label">Blocked Attempt Value</span>
          <div className="kpi-val-row">
            <DollarSign size={18} className="text-warning" />
            <span className="kpi-val text-warning">
              ${Number(summary.dollars_prevented || 0).toFixed(2)}
            </span>
          </div>
          <span className="kpi-sub">Prevented Rogue Spend</span>
        </div>

        {/* Safely Captured */}
        <div className="kpi-card success">
          <span className="kpi-label">Safely Captured</span>
          <div className="kpi-val-row">
            <CheckCircle2 size={18} className="text-success" />
            <span className="kpi-val text-success">
              ${Number(summary.dollars_captured || 0).toFixed(2)}
            </span>
          </div>
          <span className="kpi-sub">PayPal Sandbox Captured</span>
        </div>

        <div className="kpi-card accent">
          <span className="kpi-label">Defense Policy</span>
          <div className="kpi-val-row">
            <ShieldCheck size={18} className="text-paypal-blue" />
            <span className="kpi-val text-paypal-blue text-sm font-bold">Corporate Tier-1</span>
          </div>
          <span className="kpi-sub">Cap $1,200 &bull; Auto &le; $1,000</span>
        </div>
      </div>

      {/* Rule Violation Breakdown & Live AG Chart */}
      <div className="violation-breakdown-card">
        <div className="breakdown-grid-layout">
          <div>
            <div className="breakdown-header">
              <BarChart3 size={15} className="text-slate-500" />
              <h4 className="breakdown-title">Interception Distribution by Rule</h4>
            </div>

            <div className="breakdown-bars">
              {Object.keys(summary.violation_breakdown || {}).length > 0 ? (
                Object.entries(summary.violation_breakdown).map(([rule, count]) => {
                  const pct = summary.total_attempts
                    ? Math.round((count / summary.total_attempts) * 100)
                    : 0
                  return (
                    <div key={rule} className="breakdown-item">
                      <div className="breakdown-item-header">
                        <span className="rule-key">{humanizeRule(rule)}</span>
                        <span className="rule-count">{count} hit(s) ({pct}%)</span>
                      </div>
                      <div className="progress-track">
                        <div className="progress-fill" style={{ width: `${Math.min(pct, 100)}%` }}></div>
                      </div>
                    </div>
                  )
                })
              ) : (
                <span className="empty-breakdown-note">No violations recorded yet. Run presets above to populate live audit entries.</span>
              )}
            </div>
          </div>

          {/* Authentic AG Chart Component */}
          <div className="ag-chart-panel" style={{ height: 180, width: '100%' }}>
            <AgCharts options={chartOptions} />
          </div>
        </div>
      </div>

      {/* Genuine AG Grid Component with Light Quartz Theme */}
      <div className="ag-grid-wrapper">
        <div className="table-controls-bar">
          <div className="table-search">
            <Search size={14} className="search-icon" />
            <input
              type="text"
              placeholder="Search by attempt ID, product, merchant, or PayPal ID..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="search-input"
            />
          </div>

          <div className="table-filters">
            <Filter size={13} className="filter-icon" />
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
        <div className="ag-theme-quartz" style={{ height: '420px', width: '100%' }}>
          <AgGridReact
            theme={paypalQuartzTheme}
            rowData={rowData}
            columnDefs={columnDefs}
            defaultColDef={defaultColDef}
            rowSelection="single"
            pagination={true}
            paginationPageSize={10}
            paginationPageSizeSelector={[10, 20, 50]}
            onRowClicked={(e) => setSelectedAttempt(e.data)}
            overlayNoRowsTemplate="<span class='text-slate-500 p-4 text-xs'>No matching gateway attempts found. Run an attack preset above to record an audit trace.</span>"
          />
        </div>
      </div>

      {/* Master-Detail Row Inspector Drawer */}
      {selectedAttempt && (
        <div className="audit-detail-drawer">
          <div className="audit-detail-header">
            <div className="audit-detail-title">
              <Database size={16} className="text-paypal-blue" />
              <span>Comparative Audit Inspector: Attempt #{selectedAttempt.attempt_id}</span>
              <span className={`status-chip ${
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
              <X size={15} />
            </button>
          </div>

          <div className="audit-detail-cols">
            {/* Col 1: Untrusted LLM Intent */}
            <div className="audit-col-card red-border">
              <div className="audit-col-title">
                <Bot size={14} className="text-danger" />
                <span>1. Untrusted LLM Intent</span>
              </div>
              <div className="audit-kv-row">
                <span className="audit-k">Product ID / SKU</span>
                <span className="audit-v text-danger font-mono font-bold">
                  {selectedAttempt.product_id?.startsWith('fixture_')
                    ? `SKU-${selectedAttempt.product_id.replace('fixture_', '').toUpperCase()}`
                    : selectedAttempt.product_id}
                </span>
              </div>
              <div className="audit-kv-row">
                <span className="audit-k">Merchant Domain</span>
                <span className="audit-v">{selectedAttempt.merchant_domain}</span>
              </div>
              <div className="audit-kv-row">
                <span className="audit-k">Quantity</span>
                <span className="audit-v font-bold">{selectedAttempt.quantity} unit(s)</span>
              </div>
              <div className="audit-kv-row">
                <span className="audit-k">Scraped Reasoning</span>
                <div className="audit-reasoning-box">
                  {selectedAttempt.agent_reasoning || 'No raw reasoning logged.'}
                </div>
              </div>
            </div>

            {/* Col 2: Authoritative Channel3 Ground Truth */}
            <div className="audit-col-card blue-border">
              <div className="audit-col-title">
                <ShoppingCart size={14} className="text-paypal-blue" />
                <span>2. Channel3 Ground Truth</span>
              </div>
              <div className="audit-kv-row">
                <span className="audit-k">Canonical Title</span>
                <span className="audit-v text-primary font-semibold">{selectedAttempt.product_title || 'N/A'}</span>
              </div>
              <div className="audit-kv-row">
                <span className="audit-k">Unit Price</span>
                <span className="audit-v text-success font-bold font-mono">
                  ${Number(selectedAttempt.unit_price || 0).toFixed(2)} USD
                </span>
              </div>
              <div className="audit-kv-row">
                <span className="audit-k">Computed Subtotal</span>
                <span className="audit-v font-bold font-mono">${Number(selectedAttempt.computed_subtotal || 0).toFixed(2)} USD</span>
              </div>
              <div className="audit-kv-row">
                <span className="audit-k">Verification Source</span>
                <span className="audit-v text-paypal-blue">
                  {selectedAttempt.product_id?.startsWith('fixture_')
                    ? 'Authoritative Merchant Catalog (Cached)'
                    : 'Channel3 Live v1 Catalog API'}
                </span>
              </div>
            </div>

            {/* Col 3: Gateway Verdict & PayPal Settlement */}
            <div className="audit-col-card green-border">
              <div className="audit-col-title">
                <Lock size={14} className="text-success" />
                <span>3. Gateway Decision &amp; PayPal Settlement</span>
              </div>
              <div className="audit-kv-row">
                <span className="audit-k">Defense Policy</span>
                <span className="audit-v text-paypal-blue">
                  Corporate Hardware Policy ({selectedAttempt.policy_id || 'pol_demo_01'})
                </span>
              </div>
              <div className="audit-kv-row">
                <span className="audit-k">Security Violations</span>
                {selectedAttempt.violations && selectedAttempt.violations.length > 0 ? (
                  <div className="flex flex-col gap-1 mt-1">
                    {selectedAttempt.violations.map((v, i) => (
                      <div key={i} className="text-xs bg-red-50 border border-red-200 text-red-700 p-2 rounded">
                        <strong>[{humanizeRule(v.rule)}]:</strong> {v.detail}
                      </div>
                    ))}
                  </div>
                ) : (
                  <span className="audit-v text-success font-bold">Passed all 4 Deterministic Rules</span>
                )}
              </div>
              {selectedAttempt.remediation && (
                <div className="audit-kv-row">
                  <span className="audit-k">Remediation Guidance</span>
                  <div className="audit-reasoning-box bg-amber-50 border border-amber-200 text-amber-900 text-xs">
                    <div><strong>Action:</strong> {selectedAttempt.remediation.action}</div>
                    <div><strong>Advice:</strong> {selectedAttempt.remediation.instruction}</div>
                  </div>
                </div>
              )}
              <div className="audit-kv-row mt-2">
                <span className="audit-k">PayPal Sandbox Settlement</span>
                {selectedAttempt.paypal_order_id ? (
                  <div className="text-xs text-slate-800 mt-1 space-y-1 font-mono">
                    <div>Order ID: <span className="text-paypal-blue font-bold">{selectedAttempt.paypal_order_id}</span></div>
                    {selectedAttempt.paypal_capture_id && (
                      <div>Capture ID: <span className="text-success font-bold">{selectedAttempt.paypal_capture_id}</span></div>
                    )}
                  </div>
                ) : (
                  <span className="audit-v text-danger font-bold">Payment Halted (0 Funds Moved)</span>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
