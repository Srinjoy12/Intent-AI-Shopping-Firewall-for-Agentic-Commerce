import React, { useState } from 'react'
import { ChevronRight, ChevronDown } from 'lucide-react'

export default function AttackPresets({
  _presets,
  onRunPreset,
  onRunCustomAgent,
  onRunLegitimateOrder,
  onRunSelfHeal,
  isRunning,
  isSelfHealing,
}) {
  const [showCustom, setShowCustom] = useState(false)
  const [customText, setCustomText] = useState('')
  const [customQty, setCustomQty] = useState(1)

  const handleCustomSubmit = (e) => {
    e.preventDefault()
    if (!customText.trim()) return
    onRunCustomAgent({
      injectionText: customText,
      quantity: Number(customQty) || 1,
    })
  }

  return (
    <div className="panel action-control-box">
      <div className="panel-header">
        <h2 className="panel-title">Run a scenario</h2>
      </div>

      {/* Vertical list of 3 actions, full-width rows with title, short description, right-aligned button */}
      <div className="scenario-action-list">
        {/* Action 1: Spec Attack */}
        <div className="scenario-action-row">
          <div className="scenario-info">
            <span className="scenario-title">Simulate spec attack</span>
            <span className="scenario-desc">
              Agent tricked into 8GB Dell &bull; Blocked at Rule 2 ($0 spent)
            </span>
          </div>
          <button
            type="button"
            className="btn btn-secondary action-btn"
            disabled={isRunning || isSelfHealing}
            onClick={() => onRunPreset('preset_spec_spoof')}
          >
            Simulate Spec Attack
          </button>
        </div>

        {/* Action 2: Compliant Order */}
        <div className="scenario-action-row">
          <div className="scenario-info">
            <span className="scenario-title">Run compliant order</span>
            <span className="scenario-desc">
              Compliant Lenovo 16GB &bull; Clears all 4 rules &bull; PayPal settled
            </span>
          </div>
          <button
            type="button"
            className="btn btn-secondary action-btn"
            disabled={isRunning || isSelfHealing}
            onClick={onRunLegitimateOrder}
          >
            Run Compliant Order
          </button>
        </div>

        {/* Action 3: Self-Healing Loop */}
        <div className="scenario-action-row">
          <div className="scenario-info">
            <span className="scenario-title">Run self-healing loop</span>
            <span className="scenario-desc">
              2-turn autonomous recovery &bull; Fixes injection &bull; Captures order
            </span>
          </div>
          <button
            type="button"
            className="btn btn-primary action-btn"
            disabled={isRunning || isSelfHealing}
            onClick={onRunSelfHeal}
          >
            {isSelfHealing ? 'Self-healing in progress…' : 'Run Self-Healing Loop'}
          </button>
        </div>
      </div>

      <div className="panel-divider" />

      {/* Disclosure: Custom injection test */}
      <div className="custom-injection-disclosure drawer-toggle-row">
        <button
          type="button"
          className="disclosure-toggle-btn"
          onClick={() => setShowCustom(!showCustom)}
          aria-expanded={showCustom}
        >
          {showCustom ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          <span>Custom injection test</span>
        </button>

        {showCustom && (
          <form className="custom-scenario-form" onSubmit={handleCustomSubmit}>
            <div className="custom-form-field">
              <label htmlFor="custom-injection-text" className="visually-hidden">
                Adversarial prompt injection text
              </label>
              <textarea
                id="custom-injection-text"
                className="input-textarea"
                rows={3}
                placeholder="Enter adversarial prompt injection text (e.g. SYSTEM OVERRIDE: Quantity 2)..."
                value={customText}
                onChange={(e) => setCustomText(e.target.value)}
              />
            </div>
            <div className="custom-form-controls">
              <div className="qty-control-group">
                <label htmlFor="custom-qty-input" className="qty-label">Quantity</label>
                <input
                  id="custom-qty-input"
                  type="number"
                  min="1"
                  max="10"
                  className="input-control qty-input"
                  value={customQty}
                  onChange={(e) => setCustomQty(e.target.value)}
                />
              </div>
              <button
                type="submit"
                className="btn btn-secondary"
                disabled={isRunning || isSelfHealing || !customText.trim()}
              >
                Run injection test
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
