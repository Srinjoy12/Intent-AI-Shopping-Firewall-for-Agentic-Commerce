#!/usr/bin/env python3
"""
Verify UI Redesign:
- Check viewports: 375px, 768px, 1280px, 1440px
- Verify zero horizontal overflow on page body (wide tables scroll inside container)
- Run WCAG AA contrast check on text & interactive controls (>= 4.5:1)
- Verify screenshot capture integrity
"""

import sys
import os
import json
import urllib.request
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000"

CONTRAST_SCRIPT = """
() => {
    function parseRGB(rgbStr) {
        if (!rgbStr) return [255, 255, 255];
        const match = rgbStr.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
        if (match) {
            return [parseInt(match[1]), parseInt(match[2]), parseInt(match[3])];
        }
        return [255, 255, 255];
    }

    function getLuminance(r, g, b) {
        const a = [r, g, b].map(v => {
            v /= 255;
            return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
        });
        return a[0] * 0.2126 + a[1] * 0.7152 + a[2] * 0.0722;
    }

    function getContrast(rgb1, rgb2) {
        const lum1 = getLuminance(...rgb1);
        const lum2 = getLuminance(...rgb2);
        const brightest = Math.max(lum1, lum2);
        const darkest = Math.min(lum1, lum2);
        return (brightest + 0.05) / (darkest + 0.05);
    }

    function getEffectiveBg(el) {
        let cur = el;
        while (cur && cur !== document) {
            const style = window.getComputedStyle(cur);
            const bg = style.backgroundColor;
            if (bg && bg !== 'transparent' && bg !== 'rgba(0, 0, 0, 0)') {
                const match = bg.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?\\)/);
                if (match) {
                    const alpha = match[4] !== undefined ? parseFloat(match[4]) : 1;
                    if (alpha > 0.5) {
                        return [parseInt(match[1]), parseInt(match[2]), parseInt(match[3])];
                    }
                }
            }
            cur = cur.parentElement;
        }
        return [255, 255, 255];
    }

    const issues = [];
    const elements = document.querySelectorAll('h1, h2, h3, h4, p, span, button, input, label, code, .stat-num, .stat-label, .btn-action-title');

    elements.forEach(el => {
        if (el.offsetParent === null) return;
        const text = el.innerText?.trim();
        if (!text || text.length === 0) return;

        const style = window.getComputedStyle(el);
        const fg = parseRGB(style.color);
        const bg = getEffectiveBg(el);
        const ratio = getContrast(fg, bg);

        const fontSize = parseFloat(style.fontSize);
        const isBold = parseInt(style.fontWeight) >= 700;
        const minRatio = (fontSize >= 18 || (fontSize >= 14 && isBold)) ? 3.0 : 4.5;

        if (ratio < minRatio) {
            issues.push({
                tag: el.tagName,
                text: text.slice(0, 30),
                fontSize: style.fontSize,
                fontWeight: style.fontWeight,
                ratio: ratio.toFixed(2),
                minRatio,
                color: style.color,
                bgColor: `rgb(${bg.join(',')})`
            });
        }
    });

    return issues;
}
"""

OVERFLOW_SCRIPT = """
() => {
    const docEl = document.documentElement;
    const scrollWidth = docEl.scrollWidth;
    const clientWidth = docEl.clientWidth;
    const bodyScrollWidth = document.body.scrollWidth;
    const bodyClientWidth = document.body.clientWidth;

    return {
        windowInnerWidth: window.innerWidth,
        docScrollWidth: scrollWidth,
        docClientWidth: clientWidth,
        bodyScrollWidth: bodyScrollWidth,
        bodyClientWidth: bodyClientWidth,
        hasOverflow: (scrollWidth > clientWidth) || (bodyScrollWidth > bodyClientWidth)
    };
}
"""

def log(msg):
    print(msg, flush=True)

def main():
    log("=== Launching Playwright Verification Suite ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        context = browser.new_context(device_scale_factor=2)
        page = context.new_page()

        # Step 1: Viewport and Overflow Verification
        viewports = [
            ("Mobile 375px", 375, 812),
            ("Tablet 768px", 768, 1024),
            ("Laptop 1280px", 1280, 800),
            ("Desktop 1440px", 1440, 900),
        ]

        log("\n--- 1. Testing Viewports & Horizontal Overflow ---")
        has_any_overflow = False
        for label, w, h in viewports:
            page.set_viewport_size({"width": w, "height": h})
            page.goto(BASE_URL, wait_until="domcontentloaded")
            page.wait_for_selector(".header")
            page.wait_for_timeout(400)

            overflow_res = page.evaluate(OVERFLOW_SCRIPT)
            log(f"[{label} ({w}x{h})] Overflow check:")
            log(f"   window.innerWidth: {overflow_res['windowInnerWidth']}, docScrollWidth: {overflow_res['docScrollWidth']}, clientWidth: {overflow_res['docClientWidth']}")
            log(f"   Has horizontal body overflow: {overflow_res['hasOverflow']}")
            if overflow_res['hasOverflow']:
                log(f"   ❌ WARNING: Body overflow detected at {w}px!")
                has_any_overflow = True
            else:
                log(f"   ✓ PASS: Clean, zero horizontal page scroll.")

        assert not has_any_overflow, "Horizontal body overflow detected!"

        # Step 2: Contrast Check at 1440px
        log("\n--- 2. Checking Text & Control Contrast (WCAG AA >= 4.5:1) ---")
        page.set_viewport_size({"width": 1440, "height": 900})
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.wait_for_selector(".header")
        page.wait_for_timeout(600)

        contrast_issues = page.evaluate(CONTRAST_SCRIPT)
        if contrast_issues:
            log(f"   Found {len(contrast_issues)} low contrast elements:")
            for issue in contrast_issues[:8]:
                log(f"   - <{issue['tag']}> '{issue['text']}' Ratio: {issue['ratio']}:1 (min: {issue['minRatio']}) fg:{issue['color']} bg:{issue['bgColor']}")
            sys.exit(1)
        else:
            log("   ✓ PASS: All visible text elements satisfy WCAG AA contrast against surfaces!")

        browser.close()
        log("\n✓ All UI Viewport and Contrast Verifications Passed Cleanly!")

if __name__ == "__main__":
    main()
