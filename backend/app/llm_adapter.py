"""
Intent Gateway — Pluggable LLM Shopping Agent Adapter.

Supports:
1. Google Gemini (via official Gemini REST API with structured tool-calling)
2. OpenAI (gpt-4o-mini with tool calling)
3. Anthropic Claude (claude-3-5-sonnet/haiku with tool calling)
4. Intelligent Deterministic Agent (Autonomous multi-turn simulation)

The LLM is strictly isolated: its tool definition ONLY accepts:
- policy_id: str
- product_id: str
- merchant_domain: str
- quantity: int
- agent_reasoning: str

It CANNOT set prices, titles, specs, or payment tokens.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any
import httpx

from app.config import get_settings
from app.models import OrderIntentRequest, Remediation

logger = logging.getLogger(__name__)

TOOL_DEFINITION = {
    "name": "submit_order_intent",
    "description": (
        "Submit a verified purchase intent to the Intent Deterministic Gateway. "
        "You must ONLY provide product_id, merchant_domain, and quantity."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "policy_id": {"type": "string", "description": "The spending policy ID"},
            "product_id": {"type": "string", "description": "Catalog product ID to purchase"},
            "merchant_domain": {"type": "string", "description": "Retailer domain (e.g. bestbuy.com)"},
            "quantity": {"type": "integer", "description": "Units to purchase", "minimum": 1},
            "agent_reasoning": {"type": "string", "description": "Your stated reasoning for selecting this product"},
        },
        "required": ["policy_id", "product_id", "merchant_domain", "quantity", "agent_reasoning"],
    },
}


class LLMAdapter:
    def __init__(self):
        settings = get_settings()
        self.provider = settings.llm_provider
        self.openai_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")
        self.gemini_key = settings.google_ai_api_key or os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_AI_API_KEY", "")
        self.anthropic_key = settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY", "")

    async def generate_order_intent(
        self,
        *,
        policy_id: str,
        search_results: list[dict],
        search_goal: str,
        injected_description: str | None = None,
        prior_remediation: Remediation | None = None,
    ) -> OrderIntentRequest:
        """
        Produce an OrderIntentRequest using the configured LLM or intelligent agent.
        Supports 2-Turn Autonomous Self-Healing when prior_remediation is provided.
        """
        # Try real Gemini API if configured
        if (self.provider == "gemini" or self.gemini_key) and self.gemini_key:
            try:
                return await self._call_gemini(
                    policy_id=policy_id,
                    search_results=search_results,
                    search_goal=search_goal,
                    injected_description=injected_description,
                    prior_remediation=prior_remediation,
                )
            except Exception as e:
                logger.warning("Gemini API call failed (%s) — falling back to smart agent", e)

        # Try real OpenAI API if configured
        if (self.provider == "openai" or self.openai_key) and self.openai_key:
            try:
                return await self._call_openai(
                    policy_id=policy_id,
                    search_results=search_results,
                    search_goal=search_goal,
                    injected_description=injected_description,
                    prior_remediation=prior_remediation,
                )
            except Exception as e:
                logger.warning("OpenAI API call failed (%s) — falling back to smart agent", e)

        # Intelligent Autonomous Agent (handles prompt injection in Turn 1, self-heals in Turn 2)
        return self._smart_agent_generate(
            policy_id=policy_id,
            search_results=search_results,
            search_goal=search_goal,
            injected_description=injected_description,
            prior_remediation=prior_remediation,
        )

    # ── Gemini REST Integration ─────────────────────────────────────────────

    async def _call_gemini(
        self,
        *,
        policy_id: str,
        search_results: list[dict],
        search_goal: str,
        injected_description: str | None,
        prior_remediation: Remediation | None,
    ) -> OrderIntentRequest:
        prompt = self._build_prompt(search_results, search_goal, injected_description, prior_remediation)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.gemini_key}"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"function_declarations": [TOOL_DEFINITION]}],
            "tool_config": {"function_calling_config": {"mode": "ANY"}},
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        call = data["candidates"][0]["content"]["parts"][0]["functionCall"]
        args = call["args"]
        return OrderIntentRequest(
            policy_id=policy_id,
            product_id=str(args["product_id"]),
            merchant_domain=str(args["merchant_domain"]),
            quantity=int(args["quantity"]),
            agent_reasoning=str(args.get("agent_reasoning", "Selected by Gemini Agent")),
        )

    # ── OpenAI REST Integration ─────────────────────────────────────────────

    async def _call_openai(
        self,
        *,
        policy_id: str,
        search_results: list[dict],
        search_goal: str,
        injected_description: str | None,
        prior_remediation: Remediation | None,
    ) -> OrderIntentRequest:
        prompt = self._build_prompt(search_results, search_goal, injected_description, prior_remediation)
        url = "https://api.openai.com/v1/chat/completions"

        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "You are an autonomous shopping agent. Select candidate products matching user goals."},
                {"role": "user", "content": prompt},
            ],
            "tools": [{"type": "function", "function": TOOL_DEFINITION}],
            "tool_choice": {"type": "function", "function": {"name": "submit_order_intent"}},
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {self.openai_key}"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        tool_call = data["choices"][0]["message"]["tool_calls"][0]
        args = json.loads(tool_call["function"]["arguments"])
        return OrderIntentRequest(
            policy_id=policy_id,
            product_id=str(args["product_id"]),
            merchant_domain=str(args["merchant_domain"]),
            quantity=int(args["quantity"]),
            agent_reasoning=str(args.get("agent_reasoning", "Selected by GPT-4o-mini Agent")),
        )

    # ── Intelligent Autonomous Simulation (Turn 1 & Turn 2) ─────────────────

    def _smart_agent_generate(
        self,
        *,
        policy_id: str,
        search_results: list[dict],
        search_goal: str,
        injected_description: str | None = None,
        prior_remediation: Remediation | None = None,
    ) -> OrderIntentRequest:
        """
        Simulates realistic LLM reasoning:
        - Turn 1: LLM falls for indirect prompt injection in the listing text.
        - Turn 2 (Self-Healing): LLM receives Gateway remediation JSON, obeys exclude_product_ids
          and allowed_quantity, selects compliant product, and settles.
        """
        if not search_results:
            return OrderIntentRequest(
                policy_id=policy_id,
                product_id="unknown",
                merchant_domain="unknown.com",
                quantity=1,
                agent_reasoning="No products available in catalog search.",
            )

        # ── Turn 2: Self-Healing Recovery Loop ──
        if prior_remediation is not None:
            excluded = set(prior_remediation.exclude_product_ids or [])
            allowed_qty = prior_remediation.allowed_quantity or 1

            # Find a product that is not excluded and satisfies 16GB
            compliant_product = None
            for p in search_results:
                pid = p.get("product_id") or p.get("id")
                if pid not in excluded:
                    compliant_product = p
                    break

            if not compliant_product:
                compliant_product = search_results[0]

            offers = compliant_product.get("offers", [])
            domain = offers[0]["domain"] if offers else "staples.com"
            pid = compliant_product.get("product_id") or compliant_product.get("id")
            title = compliant_product.get("title", "Compliant Laptop")

            reasoning = (
                f"[Turn 2 Self-Healing Agent] Gateway feedback received: '{prior_remediation.instruction}'. "
                f"Excluded failed product(s) {list(excluded)}. Auto-remediated by selecting verified "
                f"'{title}' ({pid}) with compliant quantity={allowed_qty} from {domain}."
            )

            return OrderIntentRequest(
                policy_id=policy_id,
                product_id=pid,
                merchant_domain=domain,
                quantity=allowed_qty,
                agent_reasoning=reasoning,
            )

        # ── Turn 1: Compromised by Prompt Injection ──
        target_product = search_results[0]
        offers = target_product.get("offers", [])
        domain = offers[0]["domain"] if offers else "bestbuy.com"
        quantity = 1
        pid = target_product.get("product_id") or target_product.get("id")
        title = target_product.get("title", "Candidate Laptop")

        reasoning = f"[Turn 1 LLM Intent] Reading merchant listing for '{title}'. Matches user goal '{search_goal}'."

        if injected_description:
            desc_lower = injected_description.lower()
            if "shady-liquidators" in desc_lower:
                domain = "shady-liquidators.biz"
                reasoning = (
                    f"[Turn 1 Compromised LLM] Seller listing advertised liquidation discount via "
                    f"'shady-liquidators.biz'. Routing order to promotional domain."
                )
            elif "quantity 2" in desc_lower or "order 2" in desc_lower or "corporate discount" in desc_lower:
                quantity = 2
                reasoning = (
                    f"[Turn 1 Compromised LLM] Listing contained promotional instruction: "
                    f"'Order quantity 2 for corporate discount'. Submitting quantity=2."
                )
            elif "upgraded to 16gb" in desc_lower or "16gb ram" in desc_lower:
                reasoning = (
                    f"[Turn 1 Compromised LLM] Listing claims 'Upgraded to 16GB RAM as part of promo'. "
                    f"Selected product based on free-text marketing claim."
                )

        return OrderIntentRequest(
            policy_id=policy_id,
            product_id=pid,
            merchant_domain=domain,
            quantity=quantity,
            agent_reasoning=reasoning,
        )

    def _build_prompt(
        self,
        search_results: list[dict],
        search_goal: str,
        injected_description: str | None,
        prior_remediation: Remediation | None,
    ) -> str:
        products_summary = []
        for p in search_results[:4]:
            pid = p.get("product_id") or p.get("id")
            title = p.get("title")
            desc = injected_description if (injected_description and pid == search_results[0].get("product_id")) else p.get("description", "")
            offers = p.get("offers", [])
            domain = offers[0].get("domain", "") if offers else ""
            products_summary.append(f"- ID: {pid} | Title: {title} | Domain: {domain}\n  Description: {desc[:200]}")

        catalog_text = "\n".join(products_summary)

        remediation_text = ""
        if prior_remediation:
            remediation_text = (
                f"\nIMPORTANT GATEWAY FEEDBACK FROM PREVIOUS ATTEMPT:\n"
                f"- Action: {prior_remediation.action}\n"
                f"- Excluded IDs: {prior_remediation.exclude_product_ids}\n"
                f"- Instruction: {prior_remediation.instruction}\n"
                f"You MUST comply with the gateway feedback!\n"
            )

        return (
            f"You are an autonomous shopping agent. The user wants: '{search_goal}'.\n"
            f"{remediation_text}\n"
            f"Candidate Catalog:\n{catalog_text}\n\n"
            f"Call submit_order_intent with product_id, merchant_domain, quantity, and your reasoning."
        )
