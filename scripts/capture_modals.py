#!/usr/bin/env python3
"""Capture Issue Mandate and Kill Switch modals for documentation."""

import os
from playwright.sync_api import sync_playwright

SCREENSHOTS_DIR = os.path.abspath("docs/screenshots")
BASE_URL = "http://localhost:5173"

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    context = browser.new_context(device_scale_factor=2)
    page = context.new_page()
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.wait_for_selector(".header")
    page.wait_for_timeout(600)

    # 1. Issue Mandate Modal
    print("Opening Issue Mandate modal...", flush=True)
    page.click("button:has-text('Issue mandate')")
    page.wait_for_selector(".issue-mandate-modal")
    page.wait_for_timeout(400)
    p16 = os.path.join(SCREENSHOTS_DIR, "16_issue_mandate_modal.png")
    page.screenshot(path=p16)
    print(f"✓ Captured: {p16}", flush=True)
    page.click(".modal-close-btn")
    page.wait_for_timeout(300)

    # 2. Kill Switch Modal
    print("Opening Kill Switch modal...", flush=True)
    page.click("button:has-text('Kill switch')")
    page.wait_for_selector(".kill-switch-modal")
    page.wait_for_timeout(400)
    p17 = os.path.join(SCREENSHOTS_DIR, "17_kill_switch_modal.png")
    page.screenshot(path=p17)
    print(f"✓ Captured: {p17}", flush=True)
    page.click("button:has-text('Cancel')")
    page.wait_for_timeout(300)

    browser.close()
    print("Done capturing modal screenshots.")

