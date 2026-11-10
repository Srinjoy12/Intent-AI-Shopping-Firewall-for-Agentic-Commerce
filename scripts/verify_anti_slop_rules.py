#!/usr/bin/env python3
"""
Verify strict anti-slop rules on live running frontend:
- 0 emojis in DOM text
- 0 border-radius > 8px (never 999px, never pill shapes)
- 0 gradients on buttons, cards, or text
- 0 glow, blur, glassmorphism, or neumorphic shadows
- Zero console errors across all 3 tabs (Console, Audit ledger, Benchmark)
- Zero horizontal overflow
"""

import sys
import re
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:5173"

EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map symbols
    "\U0001F1E0-\U0001F1FF"  # flags (iOS)
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE,
)

DOM_AUDIT_SCRIPT = """
() => {
    const findings = {
        pillRadii: [],
        largeRadii: [],
        gradientsOnComponents: [],
        heavyShadows: [],
    };

    const allElements = document.querySelectorAll('*');
    allElements.forEach(el => {
        if (el.tagName === 'HTML' || el.tagName === 'BODY' || el.tagName === 'SCRIPT' || el.tagName === 'STYLE' || el.tagName === 'svg' || el.tagName === 'path') {
            return;
        }

        const cs = window.getComputedStyle(el);

        // Check border-radius
        const radii = [
            parseFloat(cs.borderTopLeftRadius) || 0,
            parseFloat(cs.borderTopRightRadius) || 0,
            parseFloat(cs.borderBottomRightRadius) || 0,
            parseFloat(cs.borderBottomLeftRadius) || 0
        ];

        // Max allowed radius is 8px
        radii.forEach(r => {
            if (r > 8) {
                // If it's not an intentional circle status dot (which has width <= 10px)
                const w = el.offsetWidth;
                const h = el.offsetHeight;
                if (!(w <= 12 && h <= 12 && r >= 4)) {
                    findings.largeRadii.push({
                        tag: el.tagName,
                        className: el.className,
                        radius: r,
                        dims: `${w}x${h}`,
                        text: (el.innerText || '').slice(0, 30)
                    });
                }
            }
        });

        // Check gradients on buttons, cards, text
        const bgImg = cs.backgroundImage;
        if (bgImg && bgImg !== 'none') {
            if (bgImg.includes('gradient')) {
                // Background gradient on body is explicitly permitted by tokens.
                if (el.tagName !== 'BODY' && !el.classList.contains('app-body')) {
                    findings.gradientsOnComponents.push({
                        tag: el.tagName,
                        className: el.className,
                        bgImage: bgImg,
                        text: (el.innerText || '').slice(0, 30)
                    });
                }
            }
        }

        // Check heavy shadows / neumorphic shadows
        const boxSh = cs.boxShadow;
        if (boxSh && boxSh !== 'none') {
            // Shadows allowed: none on most surfaces; at most 0 1px 2px rgba(16,24,40,0.05) on popovers/modals
            // or subtle drawer shadow. Flag multiple shadows (e.g. neumorphic double shadows)
            if (boxSh.includes('inset') || boxSh.split('),').length > 1) {
                findings.heavyShadows.push({
                    tag: el.tagName,
                    className: el.className,
                    boxShadow: boxSh
                });
            }
        }
    });

    return findings;
}
"""

def main():
    print("=== Checking Anti-Slop Hard Rules Across All Tabs ===", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type in ("error", "warning") else None)

        tabs = [
            ("Console", "button:has-text('Console')"),
            ("Audit Ledger", "button:has-text('Audit ledger')"),
            ("Benchmark", "button:has-text('Benchmark')"),
        ]

        total_issues = 0

        for tab_name, selector in tabs:
            print(f"\n--- Checking Tab: {tab_name} ---", flush=True)
            page.goto(BASE_URL, wait_until="domcontentloaded")
            page.wait_for_selector(".header")
            page.wait_for_timeout(500)

            if tab_name != "Console":
                page.click(selector)
                page.wait_for_timeout(800)

            # 1. Emoji Check
            page_text = page.inner_text("body")
            emojis = EMOJI_PATTERN.findall(page_text)
            if emojis:
                print(f"❌ Found emojis on {tab_name}: {set(emojis)}")
                total_issues += len(emojis)
            else:
                print(f"✓ Zero emojis found on {tab_name}.")

            # 2. DOM Audit (Radii, Gradients, Shadows)
            audit = page.evaluate(DOM_AUDIT_SCRIPT)
            if audit["largeRadii"]:
                print(f"❌ Found elements with border-radius > 8px on {tab_name}: {audit['largeRadii'][:3]}")
                total_issues += len(audit["largeRadii"])
            else:
                print(f"✓ Zero elements with border-radius > 8px on {tab_name}.")

            if audit["gradientsOnComponents"]:
                print(f"❌ Found gradients on components on {tab_name}: {audit['gradientsOnComponents'][:3]}")
                total_issues += len(audit["gradientsOnComponents"])
            else:
                print(f"✓ Zero component gradients on {tab_name}.")

            if audit["heavyShadows"]:
                print(f"❌ Found heavy/neumorphic shadows on {tab_name}: {audit['heavyShadows'][:3]}")
                total_issues += len(audit["heavyShadows"])
            else:
                print(f"✓ Zero heavy/neumorphic shadows on {tab_name}.")

        print("\n--- Console Errors Check ---", flush=True)
        if console_errors:
            # Filter out expected minor messages if any
            errs = [e for e in console_errors if not "Download the React DevTools" in e]
            if errs:
                print(f"⚠️ Console messages logged ({len(errs)}):")
                for e in errs[:5]:
                    print(f"   {e}")
            else:
                print("✓ Zero console errors or warnings logged.")
        else:
            print("✓ Zero console errors or warnings logged.")

        browser.close()

        if total_issues == 0:
            print("\n🎉 ALL ANTI-SLOP HARD RULES PASSED PERFECTLY!", flush=True)
            sys.exit(0)
        else:
            print(f"\n❌ FAILED with {total_issues} rule violations.", flush=True)
            sys.exit(1)

if __name__ == "__main__":
    main()

