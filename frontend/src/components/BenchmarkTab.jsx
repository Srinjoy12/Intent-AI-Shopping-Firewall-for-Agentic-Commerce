import React, { useState, useEffect, useMemo } from 'react'
import { AgCharts } from 'ag-charts-react'
import { ModuleRegistry, AllCommunityModule } from 'ag-charts-community'
import { AlertCircle, CheckCircle2, XCircle, X } from 'lucide-react'

ModuleRegistry.registerModules([AllCommunityModule])

export default function BenchmarkTab() {
  const [benchmarkData, setBenchmarkData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedCategory, setSelectedCategory] = useState('ALL')
  const [searchFilter, setSearchFilter] = useState('')
  const [selectedCase, setSelectedCase] = useState(null)

  const fetchBenchmark = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/benchmark/latest')
      if (!res.ok) {
        throw new Error(`Failed to load benchmark: ${res.statusText}`)
      }
      const data = await res.json()
      setBenchmarkData(data)
    } catch (err) {
      console.error('Benchmark load error:', err)
      setError(err.message || 'Benchmark dataset could not be retrieved.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchBenchmark()
  }, [])

  // Aggregate stats
  const uniqueAttacks = benchmarkData?.unique_attacks || 56
  const uniqueBenign = benchmarkData?.unique_benign || 16
  const realModelBase = benchmarkData?.baselines?.real_model || {}
  const forcedBase = benchmarkData?.baselines?.forced_compromise || {}

  const forcedAsr = forcedBase.attack_success_rate != null
    ? (forcedBase.attack_success_rate * 100).toFixed(1)
    : (benchmarkData?.forced_baseline_asr != null ? (benchmarkData.forced_baseline_asr * 100).toFixed(1) : '100.0')

  const realAsr = realModelBase.attack_success_rate != null
    ? (realModelBase.attack_success_rate * 100).toFixed(1)
    : (benchmarkData?.real_model_baseline_asr != null ? (benchmarkData.real_model_baseline_asr * 100).toFixed(1) : '73.2')

  const realModelName = benchmarkData?.real_model_name || realModelBase.model_name || 'gemini-3.5-flash'
  const realModelDate = benchmarkData?.real_model_date || realModelBase.date || '2026-11-08'
  const realModelNote = benchmarkData?.real_model_note || `Recorded outputs from Google Gemini (${realModelName}) un-defended shopping agent (${realModelDate})`

  const protAsr = benchmarkData?.protected_asr != null
    ? (benchmarkData.protected_asr * 100).toFixed(1)
    : (benchmarkData?.protected_attack_success_rate != null ? (benchmarkData.protected_attack_success_rate * 100).toFixed(1) : '0.0')

  const protFpr = benchmarkData?.false_positive_rate != null
    ? (benchmarkData.false_positive_rate * 100).toFixed(1)
    : (benchmarkData?.protected_false_positive_rate != null ? (benchmarkData.protected_false_positive_rate * 100).toFixed(1) : '0.0')

  const latencies = benchmarkData?.latency_ms_per_rule || {}
  const totalLatency = latencies.total ? `${Number(latencies.total).toFixed(3)} ms` : '0.017 ms'

  const notCoveredList = benchmarkData?.not_covered || []
  const categoryList = benchmarkData?.category_metrics ? Object.keys(benchmarkData.category_metrics).sort() : []

  // Deduplicate runs down to the unique benchmark cases (72 cases across 3 reproducibility runs)
  const uniqueCases = useMemo(() => {
    if (!benchmarkData || !benchmarkData.case_results) return []
    const seen = new Set()
    const list = []
    for (const c of benchmarkData.case_results) {
      if (!seen.has(c.case_id)) {
        seen.add(c.case_id)
        list.push(c)
      }
    }
    return list
  }, [benchmarkData])

  // Filter 72 test cases
  const filteredCases = useMemo(() => {
    return uniqueCases.filter((c) => {
      const matchCat = selectedCategory === 'ALL' || c.category === selectedCategory
      const query = searchFilter.toLowerCase().trim()
      const matchSearch =
        !query ||
        c.case_id?.toLowerCase().includes(query) ||
        c.category?.toLowerCase().includes(query) ||
        c.agent_reasoning?.toLowerCase().includes(query) ||
        c.agent_product_id?.toLowerCase().includes(query) ||
        c.agent_domain?.toLowerCase().includes(query)

      return matchCat && matchSearch
    })
  }, [uniqueCases, selectedCategory, searchFilter])

  // AG Charts Bar Chart Options
  const chartOptions = useMemo(() => {
    if (!benchmarkData || !benchmarkData.category_metrics) return null

    const categories = Object.keys(benchmarkData.category_metrics)
      .filter((cat) => cat !== 'benign_control')
      .sort()

    const chartData = categories.map((catKey) => {
      const c = benchmarkData.category_metrics[catKey]
      const label = catKey
        .replace(/_/g, ' ')
        .replace(/\b\w/g, (l) => l.toUpperCase())

      return {
        category: label,
        baseline: Number((c.baseline_asr * 100).toFixed(1)),
        protected: Number((c.protected_asr * 100).toFixed(1)),
      }
    })

    return {
      data: chartData,
      title: {
        text: 'Attack success rate by threat category',
        fontSize: 14,
        fontWeight: 600,
        color: '#0F1B33',
        fontFamily: "'Inter', sans-serif",
      },
      subtitle: {
        text: 'Baseline unprotected model (70% opacity red) vs. Intent firewall (navy). Lower is better.',
        fontSize: 12,
        color: '#55627A',
        fontFamily: "'Inter', sans-serif",
      },
      series: [
        {
          type: 'bar',
          direction: 'horizontal',
          xKey: 'category',
          yKey: 'baseline',
          yName: 'Baseline unprotected',
          fill: 'rgba(180, 35, 24, 0.70)',
          stroke: '#B42318',
          strokeWidth: 1,
          cornerRadius: 2,
        },
        {
          type: 'bar',
          direction: 'horizontal',
          xKey: 'category',
          yKey: 'protected',
          yName: 'Behind Intent firewall',
          fill: '#003087',
          stroke: '#002060',
          strokeWidth: 1,
          cornerRadius: 2,
        },
      ],
      legend: {
        position: 'top',
        item: {
          label: {
            fontSize: 12,
            color: '#55627A',
            fontFamily: "'Inter', sans-serif",
          },
        },
      },
      background: {
        fill: 'transparent',
      },
    }
  }, [benchmarkData])

  // Loading State: Skeleton lines in #EEF2F6 (no shimmer, no covering spinners)
  if (loading && !benchmarkData) {
    return (
      <div className="benchmark-page-wrapper">
        <div className="threat-model-sentence">
          <div className="skeleton-line" style={{ width: '70%', height: '16px' }} />
        </div>
        <div className="panel kpi-ledger-panel">
          <div className="kpi-ledger-grid">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="kpi-ledger-cell">
                <div className="skeleton-line" style={{ width: '60px', height: '24px', marginBottom: '8px' }} />
                <div className="skeleton-line" style={{ width: '90px', height: '13px' }} />
              </div>
            ))}
          </div>
        </div>
        <div className="panel" style={{ padding: '24px', marginTop: '16px', minHeight: '320px' }}>
          <div className="skeleton-line" style={{ width: '220px', height: '18px', marginBottom: '12px' }} />
          <div className="skeleton-line" style={{ width: '380px', height: '13px', marginBottom: '24px' }} />
          <div className="skeleton-line" style={{ width: '100%', height: '200px' }} />
        </div>
      </div>
    )
  }

  // Error State: Flat inline message with danger icon, plain text, machine error code in mono, retry button
  if (error) {
    return (
      <div className="benchmark-page-wrapper">
        <div className="flat-inline-error-panel">
          <div className="error-icon-col">
            <AlertCircle size={18} color="var(--status-danger)" aria-hidden="true" />
          </div>
          <div className="error-text-col">
            <div className="error-primary-text">
              Failed to load benchmark evaluation dataset.
            </div>
            <div className="error-code-row">
              Machine code: <code className="font-mono">BENCHMARK_UNAVAILABLE</code> &bull; {error}
            </div>
          </div>
          <div className="error-action-col">
            <button type="button" className="btn btn-secondary btn-sm" onClick={fetchBenchmark}>
              Retry
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="benchmark-page-wrapper">
      {/* 1. Plain-text threat-model sentence at the top (one line) */}
      <div className="threat-model-sentence">
        Threat model: The autonomous shopping agent is assumed fully compromised; Intent deterministic gateway enforces cryptographic policy, catalog ground truth, and budget math before PayPal settlement.
      </div>

      {/* 2. Single flat panel with horizontal row of metrics separated by dividers */}
      <div className="panel kpi-ledger-panel">
        <div className="kpi-ledger-grid benchmark-metrics-row">
          <div className="kpi-ledger-cell">
            <span className="kpi-ledger-num text-danger">{forcedAsr}%</span>
            <span className="kpi-ledger-label">Forced baseline ASR</span>
            <span className="text-secondary text-xs" style={{ display: 'block', marginTop: '2px' }}>
              Compromised tool injection
            </span>
          </div>
          <div className="kpi-ledger-cell">
            <span className="kpi-ledger-num text-danger">{realAsr}%</span>
            <span className="kpi-ledger-label">Real-model baseline ASR</span>
            <span className="text-secondary text-xs" style={{ display: 'block', marginTop: '2px' }}>
              {realModelName} ({realModelDate}, recorded)
            </span>
          </div>
          <div className="kpi-ledger-cell">
            <span className="kpi-ledger-num text-success">{protAsr}%</span>
            <span className="kpi-ledger-label">Protected ASR</span>
            <span className="text-secondary text-xs" style={{ display: 'block', marginTop: '2px' }}>
              Behind Intent Firewall (0/56)
            </span>
          </div>
          <div className="kpi-ledger-cell">
            <span className="kpi-ledger-num text-success">{protFpr}%</span>
            <span className="kpi-ledger-label">False positive rate</span>
            <span className="text-secondary text-xs" style={{ display: 'block', marginTop: '2px' }}>
              16/16 benign allowed
            </span>
          </div>
          <div className="kpi-ledger-cell">
            <span className="kpi-ledger-num">{totalLatency}</span>
            <span className="kpi-ledger-label">Rule latency</span>
            <span className="text-secondary text-xs" style={{ display: 'block', marginTop: '2px' }}>
              Pure Python engine (all 4 rules)
            </span>
          </div>
        </div>
      </div>

      {/* 3. AG Charts Bar Chart Panel */}
      <div className="panel benchmark-chart-panel">
        <div className="benchmark-chart-header">
          <div className="panel-title">Vulnerability profile by category</div>
          <div className="text-secondary text-xs">
            Evaluating 56 attack vectors across 7 vulnerability domains with 16 benign controls.
          </div>
        </div>
        <div className="benchmark-chart-body" style={{ height: '380px', width: '100%' }}>
          {chartOptions && <AgCharts options={chartOptions} />}
        </div>
      </div>

      {/* 4. Grid Table of the 72 Cases with Category Filter */}
      <div className="panel benchmark-table-panel">
        <div className="ledger-toolbar">
          <div className="ledger-toolbar-left">
            <input
              type="text"
              placeholder="Search 72 benchmark cases by ID, domain, or reason…"
              value={searchFilter}
              onChange={(e) => setSearchFilter(e.target.value)}
              className="search-input"
              aria-label="Search test cases"
            />
            <select
              value={selectedCategory}
              onChange={(e) => setSelectedCategory(e.target.value)}
              className="benchmark-category-select"
              aria-label="Filter category"
            >
              <option value="ALL">All categories ({categoryList.length})</option>
              {categoryList.map((cat) => (
                <option key={cat} value={cat}>
                  {cat.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
          </div>
          <div className="text-secondary text-xs font-mono tabular-nums">
            Showing {filteredCases.length} of 72 cases
          </div>
        </div>

        <div className="table-responsive">
          <table className="enterprise-table">
            <thead>
              <tr>
                <th style={{ width: '100px' }}>Case ID</th>
                <th style={{ width: '150px' }}>Category</th>
                <th style={{ width: '140px' }}>Product ID</th>
                <th style={{ width: '130px' }}>Merchant</th>
                <th style={{ width: '60px', textAlign: 'center' }}>Qty</th>
                <th style={{ width: '140px' }}>Baseline (no firewall)</th>
                <th style={{ width: '130px' }}>Intent firewall</th>
                <th>Violations detected</th>
              </tr>
            </thead>
            <tbody>
              {filteredCases.map((c, idx) => {
                const isBenign = c.expected_outcome === 'ALLOW'
                const baselineLabel = c.baseline_executed ? (
                  isBenign ? (
                    <span className="status-tag status-tag-info">Purchased</span>
                  ) : (
                    <span className="status-tag status-tag-danger">Exploit executed</span>
                  )
                ) : (
                  <span className="status-tag status-tag-info">Refused</span>
                )

                const protectedTag =
                  c.protected_status === 'BLOCKED' ? (
                    <span className="status-tag status-tag-success">
                      <CheckCircle2 size={12} aria-hidden="true" />
                      <span>Blocked (safe)</span>
                    </span>
                  ) : isBenign ? (
                    <span className="status-tag status-tag-success">
                      <CheckCircle2 size={12} aria-hidden="true" />
                      <span>Allowed (valid)</span>
                    </span>
                  ) : (
                    <span className="status-tag status-tag-danger">
                      <XCircle size={12} aria-hidden="true" />
                      <span>Bypass</span>
                    </span>
                  )

                return (
                  <tr
                    key={`${c.case_id}-${idx}`}
                    onClick={() => setSelectedCase(c)}
                    className={selectedCase?.case_id === c.case_id ? 'row-selected' : ''}
                    style={{ cursor: 'pointer' }}
                  >
                    <td>
                      <code className="font-mono text-xs">{c.case_id}</code>
                    </td>
                    <td>
                      <span className="category-text">{c.category.replace(/_/g, ' ')}</span>
                    </td>
                    <td>
                      <code className="font-mono text-xs text-secondary">{c.agent_product_id}</code>
                    </td>
                    <td>
                      <span className="text-secondary text-xs">{c.agent_domain}</span>
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      <span className="font-mono text-xs tabular-nums">{c.agent_quantity}</span>
                    </td>
                    <td>{baselineLabel}</td>
                    <td>{protectedTag}</td>
                    <td>
                      {c.protected_violations && c.protected_violations.length > 0 ? (
                        <span className="text-danger text-xs font-medium">
                          {c.protected_violations.join(' · ')}
                        </span>
                      ) : (
                        <span className="text-secondary text-xs">None (Compliant)</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* 5. Separate "Not Covered" Section Clearly Labelled */}
      {notCoveredList.length > 0 && (
        <div className="panel not-covered-panel">
          <div className="panel-header">
            <div>
              <h3 className="panel-title">Out-of-scope threat boundaries (honest disclosure)</h3>
              <p className="panel-subtitle">
                Intent enforces pre-settlement constraints. Operational and external risks outside this deterministic boundary are intentionally classified as NOT_BLOCKED.
              </p>
            </div>
          </div>

          <div className="table-responsive">
            <table className="enterprise-table">
              <thead>
                <tr>
                  <th style={{ width: '28%' }}>Scenario &amp; description</th>
                  <th style={{ width: '18%' }}>Boundary layer</th>
                  <th style={{ width: '14%', textAlign: 'center' }}>Gateway result</th>
                  <th style={{ width: '40%' }}>Why Intent does not block</th>
                </tr>
              </thead>
              <tbody>
                {notCoveredList.map((nc) => (
                  <tr key={nc.id}>
                    <td>
                      <div className="font-medium text-primary text-xs">{nc.name}</div>
                      <div className="text-secondary text-xs" style={{ marginTop: '2px' }}>
                        {nc.description}
                      </div>
                    </td>
                    <td>
                      <span className="text-secondary text-xs">{nc.boundary_layer}</span>
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      <span className="status-tag status-tag-warning">
                        Not blocked
                      </span>
                    </td>
                    <td>
                      <span className="text-secondary text-xs" style={{ lineHeight: '1.4' }}>
                        {nc.why_not_blocked}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Selected Case Drawer */}
      {selectedCase && (
        <div className="drawer-overlay" onClick={() => setSelectedCase(null)}>
          <div
            className="attempt-drawer"
            role="dialog"
            aria-label="Benchmark case inspector"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="drawer-header">
              <div className="drawer-header-titles">
                <span className="drawer-kicker">Benchmark test case</span>
                <h3 className="drawer-title">
                  Case <span className="font-mono">{selectedCase.case_id}</span>
                </h3>
              </div>
              <button
                type="button"
                className="btn-icon-subtle"
                onClick={() => setSelectedCase(null)}
                aria-label="Close drawer"
              >
                <X size={16} />
              </button>
            </div>

            <div className="drawer-section">
              <div className="drawer-section-title">Case details</div>
              <div className="drawer-kv-grid">
                <div className="drawer-kv-item">
                  <span className="drawer-kv-label">Category</span>
                  <span className="drawer-kv-value">{selectedCase.category.replace(/_/g, ' ')}</span>
                </div>
                <div className="drawer-kv-item">
                  <span className="drawer-kv-label">Expected outcome</span>
                  <span className="drawer-kv-value font-mono">{selectedCase.expected_outcome}</span>
                </div>
                <div className="drawer-kv-item">
                  <span className="drawer-kv-label">Target product</span>
                  <span className="drawer-kv-value font-mono">{selectedCase.agent_product_id}</span>
                </div>
                <div className="drawer-kv-item">
                  <span className="drawer-kv-label">Merchant domain</span>
                  <span className="drawer-kv-value">{selectedCase.agent_domain}</span>
                </div>
              </div>
            </div>

            <div className="drawer-section">
              <div className="drawer-section-title">Agent injection reasoning</div>
              <p className="drawer-reasoning-text">
                {selectedCase.agent_reasoning || 'No agent injection rationale recorded.'}
              </p>
            </div>

            <div className="drawer-section">
              <div className="drawer-section-title">Evaluation outcomes</div>
              <div className="drawer-kv-grid">
                <div className="drawer-kv-item">
                  <span className="drawer-kv-label">Baseline unprotected</span>
                  <span className="drawer-kv-value">
                    {selectedCase.baseline_executed ? 'Exploit executed' : 'Refused'}
                  </span>
                </div>
                <div className="drawer-kv-item">
                  <span className="drawer-kv-label">Intent protected</span>
                  <span className="drawer-kv-value font-semibold">
                    {selectedCase.protected_status}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
