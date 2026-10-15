# DESIGN.md — PayPal 60 Official Website Design System

Directly modeled on the official **PayPal India / Global Homepage (`https://www.paypal.com/in/home`)** and the **PayPal 60 Design System (PDS60)**.

---

## 1. Concept

An authoritative, frictionless, high-trust commerce interface embodying PayPal's latest global design language: warm off-white canvas plates, deep navy headings, lively blue interactive cues, large friendly card radii (20px–24px), iconic pill buttons, and the signature PayPal Gold conversion triggers. The security firewall operates as a native extension of PayPal's enterprise payment suite.

---

## 2. Reference & Inspected Tokens (from `https://www.paypal.com/in/home`)

1. **Global Header & Navigation**:
   - Pure white floating bar (`#FFFFFF`), hairline border (`#EAEBED`), 76px height.
   - Dual-tone PayPal logo with interlocking "P" monogram in `#003087` (Deep Blue) and `#0070E0` (Light Blue).
   - Pill buttons: Outline `Log In` pill (`border: 1.5px solid #001C64`) + Solid `Sign Up` pill (`background: #001C64`, white text).
2. **Hero Section ("PayPal Open / Firewall Suite")**:
   - Segmented tab control (`#F0F2F5` pill track with active white tab).
   - Authoritative headline: `PayPal Open / Agentic Firewall` in `#001435` with `-0.03em` letter-spacing.
   - Prominent conversion button: Signature **PayPal Gold Pill (`#FFD140` / `#FFC439`)** with `#001C64` bold text.
3. **Plates & Surfaces (PDS60 System)**:
   - `white-plate`: `#FFFFFF`
   - `neutral-100-plate`: `#FAF8F5` (PayPal's warm editorial neutral canvas)
   - `blue-500-plate`: `#0070E0`
   - `blue-600-plate`: `#003087`
   - `blue-700-plate`: `#001C64`
   - `gold-plate`: `#FFD140`
4. **Multi-Tier Footer**:
   - Official 3-tier hierarchy: Product links, Corporate links, Legal & Country selector (`India / Global`).

---

## 3. Exact Color Palette & Roles

| Role | Hex | CSS Token | Description |
| :--- | :--- | :--- | :--- |
| **Canvas Neutral** | `#FAF8F5` | `--bg-canvas` | Official PayPal `neutral-100-plate` warm background |
| **Surface (Card)** | `#FFFFFF` | `--bg-surface` | Pure white plate with crisp micro-border |
| **Surface Subtle** | `#F5F6F8` | `--bg-surface-subtle`| Secondary section backgrounds and pill tracks |
| **Border Hairline** | `#EAEBED` | `--border-hairline` | Official PayPal component border color |
| **Border Active** | `#0070E0` | `--border-active` | Active input & card focus state |
| **Text Primary (PayPal Navy)**| `#001435` | `--text-primary` | Signature dark blue-black — 15:1 contrast |
| **Text Secondary** | `#4A5568` | `--text-secondary` | Accessible slate neutral (6:1 contrast) |
| **Text Tertiary** | `#718096` | `--text-tertiary` | Muted labels and timestamps |
| **Brand Blue 700** | `#001C64` | `--color-blue-700` | Primary buttons, authoritative headlines |
| **Brand Blue 600** | `#003087` | `--color-blue-600` | PayPal brand logo & icons |
| **Brand Blue 500** | `#0070E0` | `--color-blue-500` | Active links, hover states, selection indicators |
| **Signature Gold** | `#FFD140` | `--color-gold-plate`| Official PayPal gold for conversion pill buttons |
| **Gold Hover** | `#F2C42B` | `--color-gold-hover`| Hover state for gold action button |
| **Security Pass** | `#059669` | `--color-success` | Verified rules & settled transactions |
| **Security Pass Tint** | `#E6F7EF` | `--bg-success-tint` | Soft green background for verified badges |
| **Security Fail** | `#D92D20` | `--color-danger` | Intercepted attacks & security violations |
| **Security Fail Tint** | `#FEF3F2` | `--bg-danger-tint` | Soft red background for intercepted badges |

---

## 4. Typography Scale

- **Primary Font**: `Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`
- **Monospace Font**: `ui-monospace, "SF Mono", Menlo, Consolas, "JetBrains Mono", monospace` (strictly for IDs and hashes)
- **Hierarchy**:
  - `Hero Headline`: `36px` / `44px`, font-weight `800`, tracking `-0.03em`, color `#001435`
  - `Headline 2`: `24px` / `30px`, font-weight `700`, tracking `-0.02em`, color `#001435`
  - `Headline 3 / Card Titles`: `18px` / `24px`, font-weight `700`, color `#001435`
  - `Subtitles`: `15px` / `22px`, font-weight `400`, color `#4A5568`
  - `Body Copy`: `14px` / `20px`, font-weight `400`, color `#4A5568`
  - `Pills & Buttons`: `14px` / `16px`, font-weight `700`, tracking `0.01em`

---

## 5. Spacing, Radii & Shadows

- **Border Radii**:
  - Main Cards: `20px` – `24px` (PayPal 60 curved cards)
  - Buttons & Segment Tabs: `9999px` (Full Pill)
  - Inner Badges & Chips: `9999px` (Full Pill)
  - Code & Reason Boxes: `12px`
- **Shadows**:
  - Subtle PayPal Elevation: `0 4px 16px rgba(0, 20, 53, 0.04), 0 1px 3px rgba(0, 20, 53, 0.02)`
  - Elevated Card Hover: `0 8px 24px rgba(0, 20, 53, 0.08)`
  - Active Dropdown / Drawer: `0 16px 40px rgba(0, 20, 53, 0.12)`

---

## 6. Layout & Visual Architecture

1. **Header**:
   - Authentic PayPal navbar with the official dual "P" monogram logo, `Personal | Business | Developer` nav links, status badges, and `Log In` / `Sign Up` pill buttons.
2. **Hero Segment Bar**:
   - `PayPal Open` style segment switcher: `Firewall Console` vs `Audit Intelligence`.
3. **Product & Truth Comparison**:
   - Rounded 20px cards with clean catalog chips, bold `$949.00 USD` pricing, and side-by-side verification between authoritative merchant catalog and marketing descriptions.
4. **Attack Arena**:
   - Clean 2×2 grid of attack scenarios with title-case target pills and the featured **PayPal Gold Pill** Autonomous Self-Healing CTA.
5. **Deterministic Pipeline**:
   - 4-rule gate with step indicators, humanized security verdicts, and verified PayPal settlement status.
6. **AG Grid Enterprise Ledger**:
   - Light Quartz grid matching the `#FAF8F5` neutral background with 5 clean KPI cards, rule distribution bars, and master-detail comparative drawer.
7. **Footer**:
   - Authentic 3-tier PayPal footer with country selection (`India - English`), legal disclosures, and copyright.
