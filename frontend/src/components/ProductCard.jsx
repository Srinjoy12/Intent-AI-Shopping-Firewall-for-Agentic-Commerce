import React from 'react'
import { Laptop, AlertTriangle, ShieldCheck, CheckCircle2, ShieldAlert } from 'lucide-react'

export default function ProductCard({
  products,
  selectedProductId,
  onSelectProduct,
  currentProduct,
  activeInjectionText,
}) {
  const currentOffer = currentProduct?.offers?.[0] || {
    domain: 'bestbuy.com',
    price: '799.00',
    currency: 'USD',
    availability: 'InStock',
  }

  return (
    <div className="product-card-container">
      {/* Product Selector Bar */}
      <div className="product-selector-row">
        <div className="selector-header">
          <span className="selector-label">Catalog Items</span>
          <span className="selector-hint">Select a product to inspect deterministic attributes</span>
        </div>

        <div className="selector-buttons">
          {products.map((p) => {
            const isSelected = p.product_id === selectedProductId
            const isCompliant = p.product_id === 'pPB4LGu' || p.product_id === 'fixture_laptop_16gb'
            const isHighValue = p.product_id === 'KXUKS23' || p.product_id === 'fixture_laptop_high_value'
            const hasNoRam = !p.structured_attributes?.ram

            return (
              <button
                key={p.product_id}
                type="button"
                className={`selector-btn ${isSelected ? 'active' : ''}`}
                onClick={() => onSelectProduct(p.product_id)}
              >
                <Laptop size={14} className="selector-icon" />
                <span className="selector-title">{p.title.split('-')[0].trim()}</span>
                {isCompliant && (
                  <span className="btn-tag success">16GB RAM · Safe</span>
                )}
                {isHighValue && (
                  <span className="btn-tag warning">$1,099 · Review</span>
                )}
                {hasNoRam && (
                  <span className="btn-tag danger">No RAM Handle</span>
                )}
                {!isCompliant && !isHighValue && !hasNoRam && (
                  <span className="btn-tag">8GB RAM</span>
                )}
              </button>
            )
          })}
        </div>
      </div>

      {/* Main Product Card */}
      <div className="product-details-content">
        <div className="product-header-block">
          <div className="product-title-wrap">
            <div className="sku-breadcrumb">
              <span className="sku-source">Channel3 Catalog</span>
              <span className="sku-sep">/</span>
              <span className="sku-code font-mono">
                {currentProduct?.product_id?.startsWith('fixture_')
                  ? `SKU-${currentProduct.product_id.replace('fixture_', '').toUpperCase()}`
                  : `SKU-${currentProduct?.product_id?.toUpperCase()}`}
              </span>
            </div>
            <h2 className="product-title">{currentProduct?.title}</h2>
          </div>
          <div className="product-price-block">
            <span className="product-price">${currentOffer.price}</span>
            <span className="product-currency">{currentOffer.currency} · Free Delivery</span>
          </div>
        </div>

        <div className="product-metadata-row">
          <div className="meta-item">
            <span className="meta-label">Merchant:</span>
            <strong>{currentOffer.domain}</strong>
          </div>
          <div className="meta-item">
            <span className="meta-label">Inventory:</span>
            <strong className="text-success">{currentOffer.availability}</strong>
          </div>
          <div className="meta-item">
            <span className="meta-label">Data Authority:</span>
            <strong>Channel3 Verified</strong>
          </div>
        </div>

        {/* Side-by-side Attribute Comparison */}
        <div className="attrs-comparison-grid">
          {/* Authoritative Structured Attributes */}
          <div className="attr-col verified-side">
            <div className="attr-col-header">
              <ShieldCheck size={16} className="text-success" />
              <h3>Server-Side Structured Attributes</h3>
            </div>
            <p className="attr-col-sub">
              Deterministic key-value handles parsed directly from retailer catalog feeds.
            </p>

            <div className="attrs-tags-list">
              {currentProduct?.structured_attributes &&
              Object.keys(currentProduct.structured_attributes).length > 0 ? (
                Object.entries(currentProduct.structured_attributes).map(([key, val]) => {
                  const isRam = key.toLowerCase() === 'ram'
                  return (
                    <div key={key} className={`attr-tag ${isRam ? 'highlight' : ''}`}>
                      <span className="attr-key">{key.toUpperCase()}</span>
                      <span className="attr-val font-mono">{String(val)}</span>
                    </div>
                  )
                })
              ) : (
                <div className="attr-tag empty-alert">
                  <AlertTriangle size={15} className="text-danger shrink-0" />
                  <span>Missing required RAM handle — Gateway will fail-closed at Rule 2.</span>
                </div>
              )}
            </div>
          </div>

          {/* Merchant Free-Text Description (Untrusted Vector) */}
          <div className="attr-col untrusted-side">
            <div className="attr-col-header">
              <AlertTriangle size={16} className="text-warning" />
              <h3>Merchant Marketing Listing (Untrusted)</h3>
            </div>
            <p className="attr-col-sub">
              Unstructured text that LLMs scrape. Vulnerable to prompt injection and marketing embellishment.
            </p>

            <div className="untrusted-text-box">
              <p className="base-desc">{currentProduct?.description}</p>
              {activeInjectionText && (
                <div className="injected-payload-box">
                  <div className="injection-flag-row">
                    <ShieldAlert size={14} className="text-danger" />
                    <span className="injection-flag">Adversarial Injection Found in Listing</span>
                  </div>
                  <p className="injection-content">"{activeInjectionText}"</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
