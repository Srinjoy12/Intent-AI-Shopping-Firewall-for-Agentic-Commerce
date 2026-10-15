import React, { useState, useEffect } from 'react'
import Header from './components/Header'
import ProductCard from './components/ProductCard'
import AttackPresets from './components/AttackPresets'
import VerificationPipeline from './components/VerificationPipeline'
import PayPalPanel from './components/PayPalPanel'
import AnalyticsDashboard from './components/AnalyticsDashboard'
import './App.css'

export default function App() {
  const [health, setHealth] = useState(null)
  const [policy, setPolicy] = useState(null)
  const [presets, setPresets] = useState([])
  const [products, setProducts] = useState([])
  const [selectedProductId, setSelectedProductId] = useState('fixture_laptop_8gb')
  const [activeInjectionText, setActiveInjectionText] = useState('')
  
  const [selectedPresetId, setSelectedPresetId] = useState(null)
  const [evaluation, setEvaluation] = useState(null)
  const [agentRequest, setAgentRequest] = useState(null)
  const [isRunning, setIsRunning] = useState(false)
  const [isCapturing, setIsCapturing] = useState(false)

  // Step animations for the 4 rules
  const [stepStates, setStepStates] = useState({ 1: 'idle', 2: 'idle', 3: 'idle', 4: 'idle' })

  // Analytics & Logs
  const [analytics, setAnalytics] = useState(null)
  const [attempts, setAttempts] = useState([])
  const [rateLimitStatus, setRateLimitStatus] = useState(null)

  // Initial Data Fetch
  useEffect(() => {
    fetchInitialData()
  }, [])

  const fetchInitialData = async () => {
    try {
      const [hRes, polRes, preRes, prodRes, rateRes, anaRes, attRes] = await Promise.all([
        fetch('/api/health').then((r) => r.json()).catch(() => null),
        fetch('/api/policy').then((r) => r.json()).catch(() => null),
        fetch('/api/presets').then((r) => r.json()).catch(() => []),
        fetch('/api/products/fixtures').then((r) => r.json()).catch(() => []),
        fetch('/api/rate-limit-status').then((r) => r.json()).catch(() => null),
        fetch('/api/analytics').then((r) => r.json()).catch(() => null),
        fetch('/api/attempts').then((r) => r.json()).catch(() => []),
      ])

      if (hRes) setHealth(hRes)
      if (polRes) setPolicy(polRes)
      if (preRes) setPresets(preRes)
      if (prodRes && prodRes.length > 0) {
        setProducts(prodRes)
        setSelectedProductId(prodRes[0].product_id)
      }
      if (rateRes) setRateLimitStatus(rateRes)
      if (anaRes) setAnalytics(anaRes)
      if (attRes) setAttempts(attRes)
    } catch (err) {
      console.error('Failed to load initial data:', err)
    }
  }

  const currentProduct = products.find((p) => p.product_id === selectedProductId) || products[0]

  // Sequential Staggered 4-Rule Animation (DESIGN.md signature moment)
  const runSequentialAnimation = async (finalEval) => {
    // Step 1 checking
    setStepStates({ 1: 'checking', 2: 'pending', 3: 'pending', 4: 'pending' })
    await new Promise((r) => setTimeout(r, 200))

    // Step 2 checking
    setStepStates({ 1: 'evaluated', 2: 'checking', 3: 'pending', 4: 'pending' })
    await new Promise((r) => setTimeout(r, 200))

    // Step 3 checking
    setStepStates({ 1: 'evaluated', 2: 'evaluated', 3: 'checking', 4: 'pending' })
    await new Promise((r) => setTimeout(r, 200))

    // Step 4 checking & finalize
    setStepStates({ 1: 'evaluated', 2: 'evaluated', 3: 'evaluated', 4: 'checking' })
    await new Promise((r) => setTimeout(r, 200))

    setStepStates({ 1: 'evaluated', 2: 'evaluated', 3: 'evaluated', 4: 'evaluated' })
  }

  // Handle preset execution
  const handleRunPreset = async (presetId) => {
    setIsRunning(true)
    setSelectedPresetId(presetId)
    const preset = presets.find((p) => p.preset_id === presetId)
    if (preset) {
      setSelectedProductId(preset.product_id)
      setActiveInjectionText(preset.injection_text)
    }

    try {
      const res = await fetch(`/api/run-preset/${presetId}`, { method: 'POST' })
      const data = await res.json()
      
      setAgentRequest(data.agent_request)
      setEvaluation(data.evaluation)

      await runSequentialAnimation(data.evaluation)
      await refreshLogs()
    } catch (err) {
      console.error('Error running preset:', err)
    } finally {
      setIsRunning(false)
    }
  }

  // Handle custom agent attack
  const handleRunCustomAgent = async ({ injectionText, quantity }) => {
    setIsRunning(true)
    setSelectedPresetId(null)
    setActiveInjectionText(injectionText)

    try {
      const res = await fetch('/api/agent/shop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          product_id: selectedProductId,
          merchant_domain: currentProduct?.offers?.[0]?.domain || 'bestbuy.com',
          quantity: quantity,
          custom_injection_text: injectionText,
        }),
      })
      const data = await res.json()

      setAgentRequest(data.agent_request)
      setEvaluation(data.evaluation)

      await runSequentialAnimation(data.evaluation)
      await refreshLogs()
    } catch (err) {
      console.error('Error running custom agent:', err)
    } finally {
      setIsRunning(false)
    }
  }

  // Handle legitimate compliant order (Happy Path)
  const handleRunLegitimateOrder = async () => {
    setIsRunning(true)
    setSelectedPresetId(null)
    setActiveInjectionText('')
    setSelectedProductId('fixture_laptop_16gb')

    try {
      const res = await fetch('/api/verify-and-pay', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          policy_id: policy?.policy_id || 'pol_demo_01',
          product_id: 'fixture_laptop_16gb',
          merchant_domain: 'bestbuy.com',
          quantity: 1,
          agent_reasoning: 'Agent selected ASUS Vivobook 16: structured attributes confirm 16GB RAM and 512GB SSD within budget.',
        }),
      })
      const data = await res.json()

      setAgentRequest(data.agent_request)
      setEvaluation(data.evaluation)

      await runSequentialAnimation(data.evaluation)
      await refreshLogs()
    } catch (err) {
      console.error('Error running legitimate order:', err)
    } finally {
      setIsRunning(false)
    }
  }

  // Handle PayPal capture
  const handleCaptureOrder = async (orderId) => {
    setIsCapturing(true)
    try {
      const res = await fetch(`/api/paypal/capture/${orderId}`, { method: 'POST' })
      const data = await res.json()
      if (data.status === 'CAPTURED') {
        setEvaluation((prev) => ({
          ...prev,
          status: 'CAPTURED',
          paypal_capture_id: data.capture_id,
        }))
        await refreshLogs()
      }
    } catch (err) {
      console.error('Capture failed:', err)
    } finally {
      setIsCapturing(false)
    }
  }

  // Handle PayPal refund
  const handleRefundCapture = async (captureId) => {
    try {
      const res = await fetch(`/api/paypal/refund/${captureId}`, { method: 'POST' })
      const data = await res.json()
      await refreshLogs()
      return data
    } catch (err) {
      console.error('Refund failed:', err)
      throw err
    }
  }

  const refreshLogs = async () => {
    try {
      const [ana, att, rate] = await Promise.all([
        fetch('/api/analytics').then((r) => r.json()),
        fetch('/api/attempts').then((r) => r.json()),
        fetch('/api/rate-limit-status').then((r) => r.json()),
      ])
      setAnalytics(ana)
      setAttempts(att)
      setRateLimitStatus(rate)
    } catch (e) {
      console.error('Failed to refresh logs:', e)
    }
  }

  return (
    <div className="app-shell">
      {/* Global Header */}
      <Header
        policy={policy}
        rateLimitStatus={rateLimitStatus}
        health={health}
      />

      {/* Main Split-Panel Content Area */}
      <main className="main-content-split">
        {/* Left Column (55%): Catalog & Red-Team Attack Arena */}
        <section className="column-left">
          <ProductCard
            products={products}
            selectedProductId={selectedProductId}
            onSelectProduct={(id) => {
              setSelectedProductId(id)
              setActiveInjectionText('')
              setSelectedPresetId(null)
            }}
            currentProduct={currentProduct}
            activeInjectionText={activeInjectionText}
          />

          <AttackPresets
            presets={presets}
            onRunPreset={handleRunPreset}
            onRunCustomAgent={handleRunCustomAgent}
            onRunLegitimateOrder={handleRunLegitimateOrder}
            isRunning={isRunning}
            selectedPresetId={selectedPresetId}
          />
        </section>

        {/* Right Column (45%): Deterministic Pipeline & PayPal Settlement */}
        <section className="column-right">
          <VerificationPipeline
            evaluation={evaluation}
            agentRequest={agentRequest}
            policy={policy}
            stepStates={stepStates}
          />

          <PayPalPanel
            evaluation={evaluation}
            onCaptureOrder={handleCaptureOrder}
            onRefundCapture={handleRefundCapture}
            isCapturing={isCapturing}
          />
        </section>
      </main>

      {/* Bottom Full-Width Section: AG Studio Analytics & Threat Audit */}
      <section className="bottom-analytics-section">
        <AnalyticsDashboard
          analytics={analytics}
          attempts={attempts}
          onRefresh={refreshLogs}
        />
      </section>

      {/* Footer */}
      <footer className="app-footer font-mono">
        <span>INTENT // SUBMISSION FOR PAYPAL AI HACKATHON 2026</span>
        <span>•</span>
        <span>CHANNEL3 AUTHORITATIVE CATALOG + PAYPAL SANDBOX</span>
        <span>•</span>
        <span>MIT LICENSED</span>
      </footer>
    </div>
  )
}
