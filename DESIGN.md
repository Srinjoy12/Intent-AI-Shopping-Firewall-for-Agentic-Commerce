# DESIGN.md — Intent: AI Shopping Firewall for Agentic Commerce

## 1. Concept

A premium, modern, minimalist enterprise security console modeled directly after the **PayPal Developer Dashboard** and **PayPal Checkout Experience**. The aesthetic conveys institutional trust, clarity, and frictionless commerce. Every product purchase attempt is intercepted by an isolated 4-rule deterministic firewall before PayPal Sandbox funds move, presented with expansive whitespace, refined typography, signature PayPal blue and gold accents, and zero visual clutter.

## 2. Reference Sites & Styles

1. **PayPal Developer Console (developer.paypal.com)** — Clean white cards, deep signature navy typography, subtle `#E2E8F0` hairline dividers, rounded pill tags, and authoritative status chips.
2. **PayPal Checkout & App (paypal.com)** — The signature PayPal blue (`#0070BA`), iconic PayPal Gold pill button (`#FFC439`), and human-friendly clear language without tech jargon.
3. **Stripe Radar / Modern Fintech** — Structured, readable fraud detection rule pipelines, transparent metrics, and interactive master-detail inspection drawers.

## 3. Color Palette & Roles

| Role | Hex | Token / CSS Variable | Description |
| :--- | :--- | :--- | :--- |
| **Canvas Background** | `#F8FAFC` | `--bg-canvas` | Soft, modern slate-tinted white canvas |
| **Surface (Card)** | `#FFFFFF` | `--bg-surface` | Pure white cards with subtle elevation |
| **Surface Raised / Hover** | `#F1F5F9` | `--bg-surface-raised` | Subtle interactive hover feedback |
| **Surface Accent Tint** | `#EBF5FF` | `--bg-accent-subtle` | Light PayPal blue wash for verified states |
| **Border Hairline** | `#E2E8F0` | `--border-subtle` | Crisp 1px structural separation |
| **Text Primary (PayPal Navy)**| `#001C3F` | `--text-primary` | Signature PayPal deep navy — ultra-crisp (14:1 contrast) |
| **Text Secondary (Muted)** | `#5B6B82` | `--text-secondary` | Sophisticated slate gray (5.5:1 contrast) |
| **Primary Accent (PayPal Blue)**| `#0070BA` | `--color-paypal-blue` | Official PayPal brand blue for links, active tabs, verified tags |
| **Primary CTA (PayPal Gold)** | `#FFC439` | `--color-paypal-gold` | Iconic PayPal yellow pill button for conversion actions |
| **CTA Hover (Gold Darker)** | `#F2B82E` | `--color-paypal-gold-hover` | Interactive state for primary CTA |
| **Security Success** | `#059669` | `--color-success` | Emerald green for passed rules & captured settlements |
| **Security Success Tint** | `#ECFDF5` | `--bg-success-subtle` | Soft green background for success pills |
| **Threat Blocked (Danger)** | `#DC2626` | `--color-danger` | Crimson red for blocked prompt injections & violations |
| **Threat Danger Tint** | `#FEF2F2` | `--bg-danger-subtle` | Soft red background for danger pills |
| **Warning / Review** | `#D97706` | `--color-warning` | Warm amber for human review & threshold notices |

## 4. Typography System

- **Typeface**: `Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`
- **Monospace (Data / IDs)**: `ui-monospace, "SF Mono", Menlo, Consolas, "JetBrains Mono", monospace`
- **Scale**:
  - App Header Title: `22px`, font-weight `700`, line-height `1.2`, tracking `-0.02em`
  - Section Headings: `16px`, font-weight `600`, line-height `1.3`, tracking `-0.01em`
  - Card Headings: `14px`, font-weight `600`, line-height `1.4`
  - Body Copy: `13px` / `14px`, font-weight `400`, line-height `1.5`, color `--text-secondary`
  - Badges & Pills: `11px` / `12px`, font-weight `600`, letter-spacing `0.02em`
  - Monospace Values: `12px` / `13px`, font-weight `500`

## 5. Spacing, Radii & Shadows

- **Spacing Scale**: `4px / 8px / 12px / 16px / 20px / 24px / 32px / 48px`
- **Border Radii**:
  - Cards & Containers: `12px` (refined modern curve)
  - Buttons & Badges: `9999px` (signature PayPal rounded pill style)
  - Textareas & Inputs: `8px`
- **Shadows**:
  - Standard Card: `0 1px 3px rgba(0, 28, 63, 0.05), 0 1px 2px rgba(0, 28, 63, 0.03)`
  - Hover Card: `0 4px 14px rgba(0, 28, 63, 0.08), 0 2px 6px rgba(0, 28, 63, 0.04)`
  - Dropdown / Drawer: `0 12px 32px -4px rgba(0, 28, 63, 0.12), 0 4px 12px -2px rgba(0, 28, 63, 0.06)`

## 6. Layout Architecture

- **Max Width**: `1440px` centered with `24px` gutter
- **Header**:
  - Top bar with PayPal-style blue badge, clean connection pills, and a crisp white policy banner with subtle slate borders.
- **Main Split (2 Columns, 55% / 45%)**:
  - **Left**: Authoritative Catalog Item + Red-Team Attack Arena (with clean rounded pill product selectors and an unmistakable PayPal Gold Self-Healing CTA).
  - **Right**: Deterministic Verification Pipeline (clean timeline cards with green checkmarks or red intercept markers) + PayPal Sandbox Settlement Card.
- **Bottom**:
  - AG Studio Analytics & Threat Audit powered by **AG Grid v36** with matching PayPal quartz light theme, 5 KPI cards with generous whitespace, and an inline Master-Detail audit drawer.

## 7. Signature Moment

When a user executes the **Autonomous 2-Turn Self-Healing Loop**:
1. **Turn 1**: The untrusted agent's attack is intercepted in real time. Rule 2 turns red with a clean pill badge, displaying the deterministic remediation JSON.
2. **Smooth Transition (1.8s)**: A clean loading spinner communicates agent self-correction.
3. **Turn 2**: The agent auto-switches to the verified 16GB laptop. All rules glow emerald green, and PayPal Sandbox captures the funds with a satisfying PayPal Gold and Green confirmation badge!
