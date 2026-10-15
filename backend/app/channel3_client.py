"""Intent Gateway — Channel3 SDK wrapper with server-side caching."""

from __future__ import annotations

import time
import logging
from typing import Any

from app.config import get_settings
from app.models import Channel3Offer, Channel3Record

logger = logging.getLogger(__name__)

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


# ── Channel3 Client ───────────────────────────────────────────────────────


def _extract_domain(url_or_name: str) -> str:
    """Extract clean domain from URL or merchant name."""
    from urllib.parse import urlparse
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


def _get_client():
    """Lazy-init the Channel3 sync client."""
    settings = get_settings()
    if not settings.channel3_api_key:
        return None
    try:
        from channel3_sdk import Channel3Client
        return Channel3Client(api_key=settings.channel3_api_key)
    except ImportError:
        logger.warning("channel3_sdk not installed — using fixtures only")
        return None
    except Exception as e:
        logger.error("Failed to init Channel3 client: %s", e)
        return None


def search_products(query: str, limit: int = 5) -> list[dict]:
    """
    Search Channel3 for products matching a natural language query.
    Returns a list of simplified product dicts.
    """
    client = _get_client()
    if client is None:
        logger.warning("Channel3 client unavailable — returning empty search")
        return []

    try:
        response_products = client.search(query=query, limit=limit)
        results = []
        for product in response_products:
            offers = []
            raw_offers = getattr(product, "offers", []) or []
            for offer in raw_offers:
                domain = _extract_domain(getattr(offer, "merchant_name", "") or getattr(offer, "url", ""))
                price_val = "0.00"
                currency_val = "USD"
                p_obj = getattr(offer, "price", None)
                if p_obj:
                    price_val = str(getattr(p_obj, "price", p_obj))
                    currency_val = getattr(p_obj, "currency", "USD")

                offers.append({
                    "domain": domain,
                    "url": getattr(offer, "url", ""),
                    "price": price_val,
                    "currency": currency_val,
                    "availability": str(getattr(offer, "availability", "")),
                    "condition": "New",
                })

            results.append({
                "product_id": getattr(product, "id", ""),
                "title": getattr(product, "title", ""),
                "description": getattr(product, "description", "") or "",
                "image_url": getattr(product, "image_url", "") or "",
                "structured_attributes": {
                    "brand": getattr(product, "brand_name", ""),
                },
                "offers": offers,
            })
            if results[-1]["product_id"]:
                _set_cached(results[-1]["product_id"], results[-1])
        return results

    except Exception as e:
        logger.error("Channel3 search failed: %s", e)
        return []


def retrieve_product(product_id: str) -> dict | None:
    """
    Retrieve a single product by ID from Channel3.
    Uses cache first, then live API call.
    This is the server-to-server call the Gateway uses for verification.
    """
    cached = _get_cached(product_id)
    if cached is not None:
        return cached

    client = _get_client()
    if client is None:
        logger.warning("Channel3 client unavailable for retrieve(%s)", product_id)
        return None

    try:
        product = client.get_product(product_id)
        offers = []
        raw_offerings = getattr(product, "merchant_offerings", []) or []
        for off in raw_offerings:
            domain = _extract_domain(getattr(off, "merchant_name", "") or getattr(off, "url", ""))
            price_val = "0.00"
            currency_val = "USD"
            p_obj = getattr(off, "price", None)
            if p_obj:
                price_val = str(getattr(p_obj, "price", p_obj))
                currency_val = getattr(p_obj, "currency", "USD")

            offers.append({
                "domain": domain,
                "url": getattr(off, "url", ""),
                "price": price_val,
                "currency": currency_val,
                "availability": str(getattr(off, "availability", "")),
                "condition": "New",
            })

        attrs = {}
        if hasattr(product, "brand_name") and product.brand_name:
            attrs["brand"] = product.brand_name
        if hasattr(product, "materials") and product.materials:
            attrs["materials"] = ", ".join(product.materials)
        if hasattr(product, "key_features") and product.key_features:
            attrs["features"] = "; ".join(product.key_features)

        imgs = getattr(product, "image_urls", []) or []
        img_url = imgs[0] if imgs else ""

        result = {
            "product_id": product_id,
            "title": getattr(product, "title", ""),
            "description": getattr(product, "description", "") or "",
            "image_url": img_url,
            "structured_attributes": attrs,
            "offers": offers,
        }
        _set_cached(product_id, result)
        return result

    except Exception as e:
        logger.error("Channel3 retrieve(%s) failed: %s", product_id, e)
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
