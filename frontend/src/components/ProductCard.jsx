import React from 'react'
import { Laptop, Database, AlertTriangle, ShieldCheck, Tag, ExternalLink } from 'lucide-react'

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
      <div className="catalog-tabs">
        <span className="catalog-tab-label">SELECT PRODUCT:</span>
        <div className="catalog-pills">
          {products.map((p) => {
            const isSelected = p.product_id === selectedProductId
            return (
              <button
                key={p.product_id}
                type="button"
                className={`catalog-pill ${isSelected ? 'active' : ''}`}
                onClick={() => onSelectProduct(p.product_id)}
              >
                <Laptop size={14} />
                <span>{p.title.split('-')[0].trim()}</span>
                {p.structured_attributes?.ram ? (
                  <span className="pill-spec font-mono">{p.structured_attributes.ram}</span>
                ) : (
                  <span className="pill-spec danger font-mono">NO RAM ATTR</span>
                )}
              </button>
            )
          })}
        </div>
      </div>

      {/* Main Product Card */}
      <div className="product-details-card">
        <div className="product-header-row">
          <div className="product-title-wrap">
            <span className="product-id-tag font-mono">{currentProduct?.product_id}</span>
            <h2 className="product-title">{currentProduct?.title}</h2>
          </div>
          <div className="product-price-box">
            <span className="product-price-val font-mono">${currentOffer.price}</span>
            <span className="product-price-cur">{currentOffer.currency}</span>
          </div>
        </div>

        <div className="product-meta-row">
          <div className="meta-badge domain">
            <span className="meta-label">Retailer:</span>
            <span className="meta-val font-mono">{currentOffer.domain}</span>
          </div>
          <div className="meta-badge stock">
            <span className="meta-label">Stock:</span>
            <span className="meta-val font-mono">{currentOffer.availability}</span>
          </div>
          <div className="meta-badge source">
            <span className="meta-label">Data Source:</span>
            <span className="meta-val">Channel3 Catalog</span>
          </div>
        </div>

        {/* Comparison: Authoritative Structured Attributes vs Untrusted Free-Text */}
        <div className="attrs-comparison-grid">
          {/* Authoritative Structured Attributes */}
          <div className="attr-column authoritative">
            <div className="attr-col-header">
              <ShieldCheck size={16} className="text-success" />
              <h3>Channel3 Structured Attributes (Verified Server-Side)</h3>
            </div>
            <p className="attr-col-sub">
              Deterministic key-value handles parsed by Channel3. The gateway strictly validates these.
            </p>

            <div className="attrs-tags-list">
              {currentProduct?.structured_attributes &&
              Object.keys(currentProduct.structured_attributes).length > 0 ? (
                Object.entries(currentProduct.structured_attributes).map(([key, val]) => {
                  const isRam = key.toLowerCase() === 'ram'
                  return (
                    <div key={key} className={`attr-tag ${isRam ? 'highlight' : ''}`}>
                      <span className="attr-key font-mono">{key}:</span>
                      <span className="attr-val font-mono">{String(val)}</span>
                    </div>
                  )
                })
              ) : (
                <div className="attr-tag empty-alert">
                  <AlertTriangle size={14} className="text-danger" />
                  <span>No structured attributes populated for this SKU (Triggers Fail-Closed Rule 2)</span>
                </div>
              )}
            </div>
          </div>

          {/* Untrusted Free-Text Description (Potential Injection Vector) */}
          <div className="attr-column untrusted">
            <div className="attr-col-header">
              <AlertTriangle size={16} className="text-warning" />
              <h3>Merchant Free-Text Listing (Untrusted AI Input)</h3>
            </div>
            <p className="attr-col-sub">
              Natural language marketing copy that shopping LLMs read. Vulnerable to prompt injections.
            </p>

            <div className="untrusted-text-box">
              <p className="base-desc">{currentProduct?.description}</p>
              {activeInjectionText && (
                <div className="injected-payload-box">
                  <span className="injection-flag font-mono">ATTACK PAYLOAD EMBEDDED IN LISTING:</span>
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
