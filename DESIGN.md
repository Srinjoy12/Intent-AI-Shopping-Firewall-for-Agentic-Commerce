# DESIGN.md — Intent AI Shopping Firewall (Minimalist Enterprise Fintech Design System)

A calm, dense, precise enterprise fintech security console for autonomous agentic commerce, built with flat surfaces, thin 1px borders, generous whitespace, strong typographic hierarchy, and restrained PayPal-inspired color.

---

## 1. Concept

A modern, minimalist enterprise security terminal that operates as the zero-trust boundary for autonomous AI agent commerce. Replacing decorative shadows and neumorphism with flat white panels, 1px crisp borders, high-contrast typography, and deterministic transaction telemetry.

---

## 2. Reference Sites & Styles

1. **Stripe Radar & Enterprise Dashboard (`dashboard.stripe.com`)**:
   - Flat white surfaces (`#FFFFFF`) with 1px subtle borders (`#E3E8EF`).
   - Generous spacing, sentence-case hierarchy, no decorative gradients.
   - Clear visual separation between authoritative merchant data and untrusted payload data.

2. **Brex / Mercury Financial Operations**:
   - Restrained palette: Deep Navy (`#003087`), Action Blue (`#0070E0`), and Slate Secondary (`#55627A`).
   - Rectangular status tags with 4px border radius, paired icons, and tinted backgrounds.
   - Strict avoidance of pill shapes, floating bubbles, or gradient buttons.

3. **Linear Institutional Density**:
   - Monospace typography (`JetBrains Mono`) strictly reserved for identifiers, hashes, and currency with tabular numbers (`tabular-nums`).
   - Underline tabs (2px solid `#0070E0`) without container boxes.
   - 150ms transitions, zero gratuitous animations, visible 2px focus outlines.

---

## 3. Exact Palette & Roles

| Role | CSS Variable | Hex / Value | Description | Contrast on Surface |
| :--- | :--- | :--- | :--- | :--- |
| **Page Background** | `--bg-page` | `linear-gradient(180deg, #FFFFFF 0%, #F3F6FA 100%)` | Very subtle vertical gradient, fixed | — |
| **Panel Surface** | `--bg-panel` | `#FFFFFF` | Flat white panel surfaces | — |
| **Border** | `--border-subtle` | `#E3E8EF` | Standard 1px panel and divider borders | 1.2:1 (structural) |
| **Strong Border** | `--border-strong` | `#CBD3DF` | Input, control, and secondary button borders | 1.8:1 (structural) |
| **Hover Row** | `--bg-hover` | `#F6F8FA` | Table row and interactive hover state | — |
| **Primary Text** | `--text-primary` | `#0F1B33` | Headings, body text, authoritative fields | 14.2:1 (AAA) |
| **Secondary Text** | `--text-secondary` | `#55627A` | Labels, metadata, helper text | 5.6:1 (AA) |
| **Disabled Text** | `--text-disabled` | `#8C97AA` | Inactive placeholders, disabled actions | 3.1:1 |
| **Brand Navy** | `--brand-navy` | `#003087` | Wordmark, section headings, table headers | 10.5:1 (AAA) |
| **Action Blue** | `--brand-blue` | `#0070E0` | Primary buttons, active underline, links | 4.8:1 (AA) |
| **Action Hover** | `--brand-hover` | `#005EC4` | Primary button hover state | 6.2:1 (AAA) |
| **Status Success Text** | `--color-success` | `#0A7D4F` | Passed rules, captured orders | 5.2:1 (AA) |
| **Status Success Bg** | `--bg-success-subtle` | `#E8F5EE` | Success badge background | — |
| **Status Danger Text** | `--color-danger` | `#B42318` | Intercepted attacks, kill switch, denied orders | 5.8:1 (AA) |
| **Status Danger Bg** | `--bg-danger-subtle` | `#FDECEA` | Danger badge background | — |
| **Status Warning Text**| `--color-warning` | `#9A5B00` | Human review hold, token countdown | 5.0:1 (AA) |
| **Status Warning Bg** | `--bg-warning-subtle`| `#FFF4E0` | Warning badge background | — |
| **Status Info Text** | `--color-info` | `#0070E0` | Sandbox tag, informational status | 4.8:1 (AA) |
| **Status Info Bg** | `--bg-info-subtle` | `#E8F1FD` | Info badge background | — |

---

## 4. Typography Scale & Font Pairing

- **Primary UI Text**: `'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`
- **Data & Numeric Text**: `'JetBrains Mono', 'SF Mono', ui-monospace, Menlo, Consolas, monospace` with `font-variant-numeric: tabular-nums`

### Scale & Hierarchy
| Level | Font Size / Line Height | Weight | Letter Spacing | Color |
| :--- | :--- | :--- | :--- | :--- |
| **Page Title / Wordmark** | `18px` / `24px` | `600` | `-0.02em` | `--brand-navy` |
| **Section Header** | `16px` / `22px` | `600` | `-0.01em` | `--brand-navy` |
| **Panel Title** | `14px` / `20px` | `600` | `normal` | `--text-primary` |
| **Body Regular** | `14px` / `21px` | `400` | `normal` | `--text-primary` |
| **Secondary / Labels** | `13px` / `18px` | `500` | `normal` | `--text-secondary` |
| **Table Column Headers**| `12px` / `16px` | `600` | `0.04em` (caps) | `--text-secondary` |
| **Status Tags / Badges**| `12px` / `16px` | `500` | `normal` | Context status color |
| **Monospace Values** | `13px` / `18px` | `500` | `normal` | `--text-primary` (tabular) |

---

## 5. Spacing Scale, Radii & Shadow Rules

### Spacing Scale
- `4px` (`--space-1`), `8px` (`--space-2`), `12px` (`--space-3`), `16px` (`--space-4`), `24px` (`--space-6`), `32px` (`--space-8`), `48px` (`--space-12`).
- Content max-width: `1360px` centered, `24px` horizontal page padding (`16px` on mobile).

### Radii Rules (Hard Anti-Slop)
- **Cards, Panels, Inputs, Buttons**: `6px` (`--radius-card`, `--radius-btn`, `--radius-input`)
- **Tags, Status Badges, Small Badges**: `4px` (`--radius-tag`)
- **NO PILL SHAPES**: Never use `border-radius: 999px` or `50%` on rectangular elements. Never exceed `8px`.

### Shadow Rules
- **Panels & Cards**: `none` (flat surfaces with `1px solid #E3E8EF` border).
- **Buttons & Inputs**: `none`.
- **Modals & Popovers**: `0 1px 2px rgba(16, 24, 40, 0.05)` at most.
- **NO NEUMORPHIC SHADOWS, NO GLOW, NO BLUR, NO GRADIENTS ON CONTROLS**.

---

## 6. Layout Concept & Signature Elements

### App Shell
- **Top Bar**: 56px height, flat white, `1px solid #E3E8EF` bottom border.
  - Left: Intent shield mark SVG + "Intent" (`#003087`, 600 weight) + "for PayPal Commerce" (`#55627A`, 13px).
  - Right: `[Sandbox]` rectangular tag, Mandate Status button with green dot and relative time ("expires in 1h 52m") toggling popover details (Ed25519 signature, policy hash with copy button, limits), secondary "Issue mandate" button, destructive-outline "Kill switch" button.
- **Underline Tabs**: Under top bar: "Console", "Audit ledger", "Benchmark" (shows plain text "72 cases", no badge pill).

### Console Tab (12-Column Grid)
- **Left Column (5/12)**:
  - **Panel "Product"**: 4-product vertical radio list with 44px rows, selected state with 2px blue border and `#E8F1FD` background. Authoritative Ground Truth comparison table with mismatch tags and monospace prompt injection evidence block.
  - **Panel "Run a scenario"**: 3 full-width action rows (primary for self-heal, secondary for spec attack and compliant order). Expandable disclosure for custom injection with textarea and quantity input.
- **Right Column (7/12)**:
  - **Panel "Verification"**: 4 deterministic security rules with 200ms reveal animation and Lucide status icons.
  - **Panel "Settlement"**: 2-column key-value layout for Idle, Blocked, Captured, and Pending Approval states with PayPal Order & Capture IDs.
  - **Panel "Gateway exchange"**: Segmented control toggle between "Agent request" and "Gateway response" with syntax-neutral mono JSON and copy button.

### Audit Ledger Tab
- Dedicated view hosting the full AG Grid threat audit trail, configured with `themeQuartz.withParams` for clean white backgrounds, `#E3E8EF` borders, 44px rows, and 4px rectangular status tags.
- Interactive row inspection opening the Attempt Inspector side drawer.

### Benchmark Tab
- Adversarial test suite results (72 cases) visualized with AG Charts comparing Baseline vs Intent protected agents across 4 attack categories with zero decorative slop.
