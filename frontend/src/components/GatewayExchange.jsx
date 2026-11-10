import React, { useState } from 'react'
import { Copy, Check } from 'lucide-react'

export default function GatewayExchange({ agentRequest, evaluation }) {
  const [activeTab, setActiveTab] = useState('request') // 'request' | 'response'
  const [copied, setCopied] = useState(false)

  const requestPayload = agentRequest || {
    mandate_id: 'demo_mandate_01',
    policy_id: 'demo_mandate_01',
    product_id: '0HQkNwE',
    merchant_domain: 'bestbuy.com',
    quantity: 1,
    agent_reasoning: 'Agent selected Lenovo ThinkPad E16: satisfies 16GB RAM and under $1,200 limit.',
  }

  const responsePayload = evaluation || {
    attempt_id: 'att_idle',
    status: 'IDLE',
    pricing_note: 'Awaiting execution of scenario intent.',
    violations: [],
  }

  const currentPayloadStr = JSON.stringify(
    activeTab === 'request' ? requestPayload : responsePayload,
    null,
    2
  )

  const handleCopy = () => {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(currentPayloadStr)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  return (
    <div className="panel gateway-exchange-panel">
      <div className="panel-header exchange-header">
        <h2 className="panel-title">Gateway exchange</h2>
        <div className="segmented-toggle" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'request'}
            className={`segment-btn ${activeTab === 'request' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('request')}
          >
            Agent request
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'response'}
            className={`segment-btn ${activeTab === 'response' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('response')}
          >
            Gateway response
          </button>
        </div>
      </div>

      <div className="exchange-code-container">
        <button
          type="button"
          className="btn-icon-copy code-copy-btn"
          onClick={handleCopy}
          title="Copy formatted JSON payload"
          aria-label="Copy JSON payload"
        >
          {copied ? <Check size={13} color="var(--status-success)" /> : <Copy size={13} />}
          <span>{copied ? 'Copied' : 'Copy JSON'}</span>
        </button>
        <pre className="exchange-code-block font-mono">
          <code>{currentPayloadStr}</code>
        </pre>
      </div>
    </div>
  )
}

