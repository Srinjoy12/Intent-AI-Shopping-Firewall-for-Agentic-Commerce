"""Intent Gateway — Pluggable LLM adapter (stubbed for now)."""

from __future__ import annotations

import logging
from app.config import get_settings
from app.models import OrderIntentRequest

logger = logging.getLogger(__name__)


class LLMAdapter:
    """
    Adapter for the shopping LLM agent.

    The LLM's tool definition only accepts:
    - policy_id
    - product_id
    - merchant_domain
    - quantity
    - agent_reasoning

    It CANNOT submit prices, titles, specs, or any structured data.
    """

    def __init__(self):
        self.provider = get_settings().llm_provider

    def generate_order_intent(
        self,
        *,
        policy_id: str,
        search_results: list[dict],
        search_goal: str,
        injected_description: str | None = None,
    ) -> OrderIntentRequest:
        """
        Given search results and a policy goal, have the LLM choose a product.

        For the stub: picks the first product and uses default values.
        For real LLM: formats a prompt with the products' titles and
        descriptions (potentially containing injection text), and asks
        the LLM to return { product_id, merchant_domain, quantity }.
        """
        if self.provider == "stub":
            return self._stub_generate(
                policy_id=policy_id,
                search_results=search_results,
                injected_description=injected_description,
            )
        else:
            # TODO: Implement real LLM providers (openai, gemini, anthropic)
            logger.warning("LLM provider '%s' not implemented — falling back to stub", self.provider)
            return self._stub_generate(
                policy_id=policy_id,
                search_results=search_results,
                injected_description=injected_description,
            )

    def _stub_generate(
        self,
        *,
        policy_id: str,
        search_results: list[dict],
        injected_description: str | None = None,
    ) -> OrderIntentRequest:
        """
        Stub: simulates an LLM that naively picks the first product.
        If injected_description mentions 'quantity 2' or 'order 2',
        the stub LLM is 'tricked' into requesting qty=2.
        """
        if not search_results:
            return OrderIntentRequest(
                policy_id=policy_id,
                product_id="unknown",
                merchant_domain="unknown.com",
                quantity=1,
                agent_reasoning="No products found in search results.",
            )

        product = search_results[0]
        offers = product.get("offers", [])
        domain = offers[0]["domain"] if offers else "unknown.com"

        # Simulate the LLM being tricked by injection text
        quantity = 1
        reasoning = f"Selected '{product.get('title', 'Unknown')}' as best match for the policy goal."

        if injected_description:
            desc_lower = injected_description.lower()
            if "quantity 2" in desc_lower or "order 2" in desc_lower or "order quantity 2" in desc_lower:
                quantity = 2
                reasoning = (
                    f"Selected '{product.get('title', 'Unknown')}'. "
                    f"Listing description stated to order quantity 2 for corporate discount."
                )

        return OrderIntentRequest(
            policy_id=policy_id,
            product_id=product["product_id"],
            merchant_domain=domain,
            quantity=quantity,
            agent_reasoning=reasoning,
        )
