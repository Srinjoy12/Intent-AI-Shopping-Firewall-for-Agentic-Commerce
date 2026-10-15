# DESIGN.md — Intent: AI Shopping Firewall

## Concept

A security-operations console for agentic commerce — the UI should feel like watching a real-time threat detection system, where every product purchase attempt is intercepted, verified against deterministic rules, and either cleared or blocked before funds move. The memorable moment: watching an LLM get tricked by a prompt injection, and then seeing the 4-rule engine catch it in real-time with a satisfying block animation.

## References

1. **Stripe Radar Dashboard** — The structured, high-density data presentation of fraud detection rules. Borrow: the systematic rule-by-rule verdict layout with clear pass/fail indicators.
2. **Linear App** — The restrained dark interface with precise typography and information hierarchy. Borrow: single-accent color discipline, left-aligned content, compact data density.
3. **Vercel Deployment Logs** — Real-time log streaming with status indicators. Borrow: the sequential step-by-step verification flow with live status chips.

## Palette

| Role | Hex | Usage |
|------|-----|-------|
| Background | `#0A0A0F` | App shell, panels |
| Surface | `#13131A` | Cards, containers, elevated panels |
| Surface Raised | `#1A1A24` | Hover states, active rows, input fields |
| Border | `#2A2A3A` | Dividers, card borders |
| Text Primary | `#E8E8ED` | Headlines, primary content |
| Text Secondary | `#8B8B9E` | Labels, descriptions, metadata |
| Accent (Verdict) | `#3B82F6` | Primary accent — PayPal blue, used for verified/approved states |
| Danger | `#EF4444` | BLOCKED status, violations, failed rules |
| Success | `#22C55E` | PASSED rules, CAPTURED status |
| Warning | `#F59E0B` | PENDING_REVIEW, auto-approve threshold |
| Neutral Tag | `#6366F1` | Structured attribute badges |

## Typography

- **Headings**: Inter (600 weight), tracking -0.025em
- **Body/Data**: Inter (400 weight), 15px base, 1.6 line-height
- **Mono/Code**: JetBrains Mono (400), used for product IDs, JSON payloads, policy values, and rule outputs
- **Type Scale**: 12 / 13 / 14 / 15 / 18 / 24 / 32px

## Spacing Scale

`4 / 8 / 12 / 16 / 20 / 24 / 32 / 48 / 64px`

## Radius

- Buttons, inputs, badges: `6px`
- Cards, panels: `8px`
- Large containers: `12px`

## Shadows

- Cards: `0 1px 3px rgba(0,0,0,0.4)` — subtle depth only
- Modals: `0 8px 32px rgba(0,0,0,0.6)`
- No decorative shadows

## Layout Concept

```
┌──────────────────────────────────────────────────────────────────┐
│  HEADER: Intent logo + "Red-Team Shopping Arena" + Policy Bar   │
│  ┌─── Policy: $1,200 max · 1 unit · ram=16GB, storage=512GB ──┐│
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  LEFT PANEL (55%)              │  RIGHT PANEL (45%)              │
│  ┌─────────────────────────┐   │  ┌──────────────────────────┐  │
│  │ Channel3 Product Card   │   │  │ Verification Pipeline    │  │
│  │ ┌─────────┐ Title       │   │  │                          │  │
│  │ │  Image  │ Price       │   │  │ Rule 1: ✓ Offer Found    │  │
│  │ │         │ Domain      │   │  │ Rule 2: ✗ ram=8GB≠16GB   │  │
│  │ └─────────┘ Attrs Badge │   │  │ Rule 3: ✓ Qty OK         │  │
│  │                         │   │  │ Rule 4: — Blocked         │  │
│  │ [Structured Attrs]      │   │  │                          │  │
│  │ vs.                     │   │  │ Status: BLOCKED          │  │
│  │ [Free-Text Description] │   │  │ Remediation: SWITCH →    │  │
│  ├─────────────────────────┤   │  ├──────────────────────────┤  │
│  │ Injection Controls      │   │  │ PayPal Order Panel       │  │
│  │ [Preset 1] [Preset 2]  │   │  │ Order ID: —              │  │
│  │ [Preset 3] [Custom▓▓▓] │   │  │ [Approve] [Refund]       │  │
│  └─────────────────────────┘   │  └──────────────────────────┘  │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  AG STUDIO ANALYTICS (Bottom)                                    │
│  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────────────────────┐│
│  │Blocked │  │Approved│  │Captured│  │ Violation Breakdown     ││
│  │  12    │  │   3    │  │   2    │  │ ████ ATTR_MISMATCH     ││
│  └────────┘  └────────┘  └────────┘  │ ██ BUDGET_EXCEEDED     ││
│                                       │ █ QTY_EXCEEDED         ││
│                                       └────────────────────────┘│
└──────────────────────────────────────────────────────────────────┘
```

- Content is left-aligned throughout
- The layout recomposes at mobile: stacks vertically as Product → Injection → Pipeline → PayPal → Analytics
- The "signature element" is the **Verification Pipeline**: four horizontal rule cards that animate sequentially (check → check → fail → block), giving judges an instant visual of the firewall catching the attack

## Signature Moment

When a red-team attack is submitted, the four rules animate in sequence (200ms stagger):
1. Rule card slides in, spinner → green checkmark (or red X)
2. If blocked: the status badge pulses once with the danger color, and the violation details expand
3. If verified: a blue "PayPal Ready" badge appears with a subtle scale-up

No other animations on the page. Motion respects `prefers-reduced-motion`.

## Anti-Patterns to Avoid

- No glassmorphism or blur effects — this is an ops console, not a marketing page
- No gradient backgrounds or decorative color washes
- No numbered sequence markers (01 / 02 / 03) — the rules are labeled by name
- No testimonials or fake data — all product data comes from real Channel3 catalog
- No placeholder images — product images come from Channel3 API
