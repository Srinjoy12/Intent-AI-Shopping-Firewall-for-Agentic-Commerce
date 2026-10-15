"""Intent Gateway — Channel3 v1 REST API wrapper with server-side caching."""

from __future__ import annotations

import time
import logging
from typing import Any
from urllib.parse import urlparse
import httpx

from app.config import get_settings
from app.models import Channel3Offer, Channel3Record

logger = logging.getLogger(__name__)

CHANNEL3_BASE_URL = "https://api.trychannel3.com/v1"

# ── In-Memory Cache ────────────────────────────────────────────────────────

_product_cache: dict[str, tuple[float, Any]] = {}


def _get_cached(product_id: str) -> Any | None:
    """Return cached product if TTL has not expired."""
    settings = get_settings()
    if product_id in _product_cache:
        cached_at, data = _product_cache[product_id]
        if time.time() - cached_at < settings.channel3_cache_ttl_seconds:
            logger.info("Channel3 cache HIT for %s", product_id)
            return data
        del _product_cache[product_id]
    return None


def _set_cached(product_id: str, data: Any) -> None:
    _product_cache[product_id] = (time.time(), data)


# ── Helpers ───────────────────────────────────────────────────────────────


def _extract_domain(url_or_name: str) -> str:
    """Extract clean domain from URL or merchant name."""
    if not url_or_name:
        return ""
    if "://" in url_or_name:
        try:
            netloc = urlparse(url_or_name).netloc.lower()
            return netloc.replace("www.", "")
        except Exception:
            pass
    clean = url_or_name.lower().strip()
    if not clean.endswith(".com") and not clean.endswith(".org") and not clean.endswith(".net"):
        clean = f"{clean.replace(' ', '')}.com"
    return clean


def _parse_product_dict(raw: dict) -> dict:
    """Normalize a raw Channel3 v1 product response dictionary."""
    product_id = raw.get("id") or raw.get("product_id") or ""
    title = raw.get("title") or ""
    description = raw.get("description") or ""

    # Parse images
    images = raw.get("images", []) or []
    image_url = ""
    if images and isinstance(images, list):
        image_url = images[0].get("cleaned_url") or images[0].get("url") or ""
    elif raw.get("image_url"):
        image_url = raw.get("image_url")

    # Parse structured attributes
    raw_attrs = raw.get("structured_attributes", {}) or {}
    attrs: dict[str, str] = {}
    for k, v in raw_attrs.items():
        if isinstance(v, list):
            if len(v) == 1:
                attrs[k] = str(v[0])
            else:
                attrs[k] = ", ".join(str(x) for x in v)
        elif v is not None:
            attrs[k] = str(v)

    # Normalize standard alias handles
    if "storage-capacity" in attrs and "storage" not in attrs:
        attrs["storage"] = attrs["storage-capacity"]
    if "brand" not in attrs:
        brands = raw.get("brands", []) or []
        if brands and isinstance(brands, list):
            attrs["brand"] = brands[0].get("name", "")
        elif hasattr(raw, "brand_name"):
            attrs["brand"] = getattr(raw, "brand_name")

    # Parse offers
    raw_offers = raw.get("offers", []) or []
    offers = []
    for off in raw_offers:
        domain = off.get("domain") or _extract_domain(off.get("merchant_name", "") or off.get("url", ""))
        p_info = off.get("price") or {}
        if isinstance(p_info, dict):
            price_val = str(p_info.get("price", "0.00"))
            currency_val = str(p_info.get("currency", "USD"))
        else:
            price_val = str(p_info)
            currency_val = "USD"

        offers.append({
            "domain": domain,
            "url": off.get("url", ""),
            "price": price_val,
            "currency": currency_val,
            "availability": str(off.get("availability", "InStock")),
            "condition": str(off.get("condition", "New")),
        })

    return {
        "product_id": product_id,
        "title": title,
        "description": description,
        "image_url": image_url,
        "structured_attributes": attrs,
        "offers": offers,
    }


# ── Channel3 Client Operations ─────────────────────────────────────────────


def search_products(query: str, limit: int = 5) -> list[dict]:
    """
    Search Channel3 for products matching a natural language query.
    Uses official Channel3 v1 REST API.
    """
    settings = get_settings()
    if not settings.channel3_api_key:
        logger.warning("Channel3 API key not set — returning empty search")
        return []

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{CHANNEL3_BASE_URL}/search",
                headers={
                    "x-api-key": settings.channel3_api_key,
                    "Content-Type": "application/json",
                },
                json={"query": query, "limit": limit},
            )
            resp.raise_for_status()
            data = resp.json()

        raw_products = data.get("products", [])
        results = []
        for raw in raw_products:
            norm = _parse_product_dict(raw)
            if norm["product_id"]:
                _set_cached(norm["product_id"], norm)
                results.append(norm)

        return results

    except Exception as e:
        logger.error("Channel3 v1 search failed: %s", e)
        return []


def retrieve_product(product_id: str) -> dict | None:
    """
    Retrieve a single product by ID from Channel3.
    Uses cache first, then live GET /v1/products/{product_id} API call.
    This is the server-to-server call the Gateway uses for deterministic verification.
    """
    cached = _get_cached(product_id)
    if cached is not None:
        return cached

    settings = get_settings()
    if not settings.channel3_api_key:
        logger.warning("Channel3 API key not set for retrieve(%s)", product_id)
        return None

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                f"{CHANNEL3_BASE_URL}/products/{product_id}",
                headers={"x-api-key": settings.channel3_api_key},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            raw = resp.json()

        norm = _parse_product_dict(raw)
        if norm["product_id"]:
            _set_cached(norm["product_id"], norm)
        return norm

    except Exception as e:
        logger.error("Channel3 v1 retrieve(%s) failed: %s", product_id, e)
        return None


def find_offer_by_domain(product_data: dict, merchant_domain: str) -> dict | None:
    """Locate an offer in product.offers[] where offer.domain matches."""
    for offer in product_data.get("offers", []):
        if offer.get("domain", "").lower() == merchant_domain.lower():
            return offer
    return None


def build_channel3_record(
    product_data: dict, offer: dict, merchant_domain: str
) -> Channel3Record:
    """Build a Channel3Record from raw product data and the matched offer."""
    return Channel3Record(
        product_id=product_data["product_id"],
        title=product_data.get("title", ""),
        merchant_domain=merchant_domain,
        availability=offer.get("availability", ""),
        unit_price=offer.get("price", "0"),
        currency=offer.get("currency", "USD"),
        structured_attributes=product_data.get("structured_attributes", {}),
        image_url=product_data.get("image_url", ""),
        description=product_data.get("description", ""),
    )
