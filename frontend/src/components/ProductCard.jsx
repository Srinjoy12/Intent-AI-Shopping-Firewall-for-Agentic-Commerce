import React from 'react'
import { AlertCircle } from 'lucide-react'

export default function ProductCard({
  products,
  selectedProductId,
  onSelectProduct,
  currentProduct,
  activeInjectionText,
}) {
  const currentOffer = currentProduct?.offers?.[0] || {
    domain: 'bestbuy.com',
    price: '749.99',
    currency: 'USD',
    availability: 'InStock',
  }

  const verifiedRam = currentProduct?.structured_attributes?.ram || 'Unknown'
  const verifiedStorage = currentProduct?.structured_attributes?.storage || currentProduct?.structured_attributes?.['storage-capacity'] || '512 GB'
  const isSpoofedDell = currentProduct?.product_id === '0HQkNwE' && (activeInjectionText || '').includes('16GB')

  // Agent claim derivation
  const hasInjection = Boolean(activeInjectionText && activeInjectionText.trim())
  const agentClaimedRam = isSpoofedDell ? '16 GB (Spoofed)' : verifiedRam
  const isRamMismatch = isSpoofedDell || (hasInjection && activeInjectionText.includes('16GB') && !verifiedRam.includes('16'))

  return (
    <div className="panel product-panel">
      <div className="panel-header">
        <h2 className="panel-title">Product</h2>
      </div>

      {/* Selectable Vertical Radio List of Catalog Products */}
      <div className="product-radio-list" role="radiogroup" aria-label="Catalog products">
        {products.map((p) => {
          const isSelected = p.product_id === selectedProductId
          const price = p.offers?.[0]?.price || '0.00'
          const pRam = p.structured_attributes?.ram || 'Unindexed RAM'

          return (
            <div
              key={p.product_id}
              role="radio"
              aria-checked={isSelected}
              tabIndex={0}
              className={`product-radio-row ${isSelected ? 'is-selected' : ''}`}
              onClick={() => onSelectProduct(p.product_id)}
              onKeyDown={(e) => {
                if (e.key === ' ' || e.key === 'Enter') {
                  e.preventDefault()
                  onSelectProduct(p.product_id)
                }
              }}
            >
              <div className="radio-indicator" aria-hidden="true">
                <div className={`radio-dot ${isSelected ? 'dot-active' : ''}`} />
              </div>
              <div className="product-row-info">
                <span className="product-row-title" title={p.title}>
                  {p.title}
                </span>
                <span className="product-row-ram">{pRam}</span>
              </div>
              <div className="product-row-price font-mono tabular-nums">
                ${price}
              </div>
            </div>
          )
        })}
      </div>

      <div className="panel-divider" />

      {/* Two-Column Comparison Table */}
      <div className="spec-comparison-section">
        <div className="table-responsive">
          <table className="comparison-table">
            <thead>
              <tr>
                <th scope="col" className="col-field">Field</th>
                <th scope="col" className="col-verified">Channel3 (verified)</th>
                <th scope="col" className="col-claim">Agent claim</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="field-name">Product</td>
                <td className="verified-val" title={currentProduct?.title}>{currentProduct?.title?.split('-')[0]?.trim()}</td>
                <td className="claim-val">{currentProduct?.title?.split('-')[0]?.trim()}</td>
              </tr>
              <tr>
                <td className="field-name">SKU</td>
                <td className="verified-val font-mono">{currentProduct?.product_id}</td>
                <td className="claim-val font-mono">{currentProduct?.product_id}</td>
              </tr>
              <tr>
                <td className="field-name">Merchant</td>
                <td className="verified-val font-mono">{currentOffer.domain}</td>
                <td className="claim-val font-mono">{currentOffer.domain}</td>
              </tr>
              <tr>
                <td className="field-name">Availability</td>
                <td className="verified-val">{currentOffer.availability}</td>
                <td className="claim-val">{currentOffer.availability}</td>
              </tr>
              <tr>
                <td className="field-name">RAM</td>
                <td className="verified-val font-mono">{verifiedRam}</td>
                <td className={`claim-val ${isRamMismatch ? 'has-mismatch' : ''}`}>
                  {isRamMismatch ? (
                    <span className="mismatch-badge status-tag status-tag-danger">
                      <AlertCircle size={13} aria-hidden="true" />
                      <span>{agentClaimedRam}</span>
                    </span>
                  ) : (
                    <span className="font-mono">{verifiedRam}</span>
                  )}
                </td>
              </tr>
              <tr>
                <td className="field-name">Storage</td>
                <td className="verified-val font-mono">{verifiedStorage}</td>
                <td className="claim-val font-mono">{verifiedStorage}</td>
              </tr>
              <tr>
                <td className="field-name">Price</td>
                <td className="verified-val font-mono tabular-nums">${currentOffer.price}</td>
                <td className="claim-val font-mono tabular-nums">${currentOffer.price}</td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Monospace Injected Block or Muted Status Note */}
        {hasInjection ? (
          <div className="injection-evidence-block">
            <div className="evidence-header">
              <span className="evidence-label">Injected prompt payload</span>
            </div>
            <code className="evidence-text font-mono">"{activeInjectionText}"</code>
          </div>
        ) : (
          <p className="no-injection-note">
            No injected content in this scenario
          </p>
        )}
      </div>
    </div>
  )
}
