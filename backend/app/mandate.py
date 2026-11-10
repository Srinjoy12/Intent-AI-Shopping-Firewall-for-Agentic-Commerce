"""
Intent Gateway — Cryptographically Signed Mandates.

Replaces mutable policies with immutable, Ed25519-signed mandates that bind
spending limits, product attributes, merchant domains, and temporal validity
to a designated agent and owner.
"""

from __future__ import annotations

import json
import hashlib
import hmac
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from pydantic import BaseModel, Field

logger = logging.getLogger("intent.mandate")

# Ephemeral dev key caching & key source tracking
_DEV_KEY: Optional[ed25519.Ed25519PrivateKey] = None
_KEY_SOURCE: str = "generated"


class MandateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class Mandate(BaseModel):
    """
    Cryptographically signed spending contract.
    All policy parameters are bound by policy_hash and Ed25519 signature.
    """

    mandate_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    owner_id: str
    agent_id: str
    max_order_total: str = Field(description="Max order total as Decimal string")
    auto_approve_under: str = Field(description="Threshold under which capture is autonomous")
    max_quantity: int = Field(default=1, ge=1)
    required_attributes: dict[str, str] = Field(default_factory=dict)
    allowed_domains: list[str] = Field(default_factory=list)
    required_availability: str = Field(default="InStock")
    
    # Cumulative & Rate Limits
    daily_limit: str = Field(default="2000.00")
    weekly_limit: str = Field(default="5000.00")
    per_merchant_limit: str = Field(default="1000.00")
    max_orders_per_hour: int = Field(default=5)
    
    # Temporal & Cryptographic fields
    issued_at: str
    expires_at: str
    nonce: str = Field(default_factory=lambda: secrets.token_hex(16))
    policy_hash: str = ""
    signature: str = ""
    status: MandateStatus = MandateStatus.ACTIVE

    # Compatibility properties for engine & legacy SpendingPolicy consumers
    @property
    def policy_id(self) -> str:
        return self.mandate_id

    @property
    def required_structured_attributes(self) -> dict[str, str]:
        return self.required_attributes

    @property
    def allowed_merchant_domains(self) -> list[str]:
        return self.allowed_domains

    @property
    def search_goal(self) -> str:
        return f"Authorized mandate {self.mandate_id} for agent {self.agent_id}"

    @property
    def currency(self) -> str:
        return "USD"


class CreateMandateRequest(BaseModel):
    """Admin-only payload to configure and sign a new Mandate."""

    mandate_id: Optional[str] = None
    owner_id: str
    agent_id: str
    max_order_total: str
    auto_approve_under: str
    max_quantity: int = 1
    required_attributes: dict[str, str] = Field(default_factory=dict)
    allowed_domains: list[str] = Field(default_factory=list)
    required_availability: str = "InStock"
    daily_limit: str = "2000.00"
    weekly_limit: str = "5000.00"
    per_merchant_limit: str = "1000.00"
    max_orders_per_hour: int = 5
    expires_in_hours: int = 24


class PublicKeyResponse(BaseModel):
    algorithm: str = "Ed25519"
    public_key: str
    encoding: str = "hex"


def compute_canonical_payload(data: dict[str, Any]) -> bytes:
    """
    Produce deterministically ordered canonical JSON bytes for hashing.
    Excludes cryptographic envelope fields: policy_hash, signature, and status.
    """
    excluded = {"policy_hash", "signature", "status"}
    filtered = {k: v for k, v in data.items() if k not in excluded}
    return json.dumps(filtered, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def compute_policy_hash(mandate_or_data: Mandate | dict[str, Any]) -> str:
    """Compute SHA-256 digest over canonical JSON representation."""
    if isinstance(mandate_or_data, Mandate):
        raw_dict = mandate_or_data.model_dump()
    else:
        raw_dict = dict(mandate_or_data)
    canonical = compute_canonical_payload(raw_dict)
    return hashlib.sha256(canonical).hexdigest()


def generate_ed25519_keypair() -> tuple[ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey]:
    """Generate a fresh Ed25519 keypair."""
    priv = ed25519.Ed25519PrivateKey.generate()
    return priv, priv.public_key()


def sign_mandate(
    mandate_data: dict[str, Any] | Mandate,
    private_key: ed25519.Ed25519PrivateKey,
) -> Mandate:
    """
    Compute policy_hash and generate Ed25519 signature over canonical hash.
    Returns a validated, signed Mandate instance.
    """
    if isinstance(mandate_data, Mandate):
        d = mandate_data.model_dump()
    else:
        d = dict(mandate_data)

    if not d.get("mandate_id"):
        d["mandate_id"] = str(uuid.uuid4())
    if not d.get("nonce"):
        d["nonce"] = secrets.token_hex(16)
    if not d.get("issued_at"):
        d["issued_at"] = datetime.now(timezone.utc).isoformat()

    # 1. Compute policy hash
    pol_hash = compute_policy_hash(d)
    d["policy_hash"] = pol_hash

    # 2. Sign the policy hash bytes
    sig_bytes = private_key.sign(pol_hash.encode("utf-8"))
    d["signature"] = sig_bytes.hex()
    d["status"] = MandateStatus.ACTIVE

    return Mandate(**d)


def verify_mandate(
    mandate: Mandate,
    public_key: ed25519.Ed25519PublicKey,
) -> tuple[bool, str | None]:
    """
    Verify Ed25519 signature, policy_hash integrity, expiration, and revocation.
    Uses constant-time comparison for all hashes and signatures.

    Returns:
        (True, None) if valid.
        (False, error_code) where error_code is one of:
            - MANDATE_REVOKED
            - MANDATE_EXPIRED
            - MANDATE_HASH_MISMATCH
            - MANDATE_SIGNATURE_INVALID
    """
    # 1. Check revocation
    if mandate.status == MandateStatus.REVOKED:
        return False, "MANDATE_REVOKED"

    # 2. Check expiration
    try:
        exp_dt = datetime.fromisoformat(mandate.expires_at)
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        if exp_dt < datetime.now(timezone.utc):
            return False, "MANDATE_EXPIRED"
    except Exception as e:
        logger.error("Failed to parse expires_at (%s): %s", mandate.expires_at, e)
        return False, "MANDATE_EXPIRED"

    # 3. Constant-time verification of policy_hash
    recomputed_hash = compute_policy_hash(mandate)
    if not hmac.compare_digest(mandate.policy_hash, recomputed_hash):
        return False, "MANDATE_SIGNATURE_INVALID"

    # 4. Verify Ed25519 signature
    try:
        sig_bytes = bytes.fromhex(mandate.signature)
        public_key.verify(sig_bytes, mandate.policy_hash.encode("utf-8"))
    except (InvalidSignature, ValueError) as e:
        logger.warning("Ed25519 signature verification failed: %s", e)
        return False, "MANDATE_SIGNATURE_INVALID"

    return True, None


def get_key_source() -> str:
    """Return whether current signing key was loaded from environment or generated ephemerally."""
    get_signing_key()
    return _KEY_SOURCE


def get_signing_key() -> ed25519.Ed25519PrivateKey:
    """
    Retrieve signing key from MANDATE_SIGNING_KEY env var or settings.
    Falls back to a session dev key with prominent warning if unset.
    """
    global _DEV_KEY, _KEY_SOURCE
    key_hex = os.environ.get("MANDATE_SIGNING_KEY", "").strip()
    if not key_hex:
        try:
            from app.config import get_settings
            key_hex = (get_settings().mandate_signing_key or "").strip()
        except Exception:
            pass

    if key_hex:
        try:
            raw_bytes = bytes.fromhex(key_hex)
            if len(raw_bytes) == 32:
                _KEY_SOURCE = "env"
                return ed25519.Ed25519PrivateKey.from_private_bytes(raw_bytes)
            else:
                logger.warning("MANDATE_SIGNING_KEY must be 32 bytes (64 hex characters). Found %d bytes.", len(raw_bytes))
        except Exception as e:
            logger.warning("Invalid MANDATE_SIGNING_KEY hex string: %s. Using ephemeral key.", e)

    if _DEV_KEY is None:
        logger.warning(
            "⚠️ [SECURITY WARNING] MANDATE_SIGNING_KEY not configured in environment. "
            "Generated ephemeral Ed25519 dev key for session. "
            "Set MANDATE_SIGNING_KEY in backend/.env for persistent signature verification across restarts."
        )
        _DEV_KEY = ed25519.Ed25519PrivateKey.generate()
        _KEY_SOURCE = "generated"

    return _DEV_KEY


DEV_ADMIN_KEYS = {
    "admin_super_secret_test_key",
    "admin",
    "password",
    "secret",
    "changeme",
    "123456",
}

DEV_MANDATE_KEYS = {
    "0" * 64,
    "dev_mandate_signing_key",
    "your_mandate_signing_key_hex_here",
}


def validate_production_configuration(settings: Optional[Any] = None) -> None:
    """
    Validate security-critical configuration when running in production.
    Raises RuntimeError if any critical key is missing or using insecure dev defaults.
    """
    if settings is None:
        try:
            from app.config import get_settings
            settings = get_settings()
        except Exception:
            return

    app_env = getattr(settings, "app_env", os.environ.get("APP_ENV", "development")).lower().strip()
    if app_env != "production":
        return

    errors: list[str] = []

    # 1. MANDATE_SIGNING_KEY check
    signing_key = (os.environ.get("MANDATE_SIGNING_KEY") or getattr(settings, "mandate_signing_key", "")).strip()
    if not signing_key:
        errors.append(
            "MANDATE_SIGNING_KEY is missing. In production, an Ed25519 signing key is required "
            "to cryptographically sign and verify mandates across restarts. "
            "Generate one with: python3 -c 'import secrets; print(secrets.token_hex(32))'"
        )
    elif signing_key in DEV_MANDATE_KEYS:
        errors.append(
            f"MANDATE_SIGNING_KEY is set to an insecure default/placeholder ('{signing_key[:10]}...'). "
            "Generate a fresh production key with: python3 -c 'import secrets; print(secrets.token_hex(32))'"
        )
    else:
        try:
            raw_bytes = bytes.fromhex(signing_key)
            if len(raw_bytes) != 32:
                errors.append(f"MANDATE_SIGNING_KEY must be exactly 32 bytes (64 hex characters), got {len(raw_bytes)} bytes.")
        except ValueError:
            errors.append("MANDATE_SIGNING_KEY must be a valid 64-character hexadecimal string.")

    # 2. ADMIN_API_KEY check
    admin_key = (os.environ.get("ADMIN_API_KEY") or getattr(settings, "admin_api_key", "")).strip()
    if not admin_key:
        errors.append(
            "ADMIN_API_KEY is missing. In production, a strong admin API key is required. "
            "Generate one with: openssl rand -hex 32"
        )
    elif admin_key in DEV_ADMIN_KEYS or admin_key.startswith(("dev_", "test_")):
        errors.append(
            f"ADMIN_API_KEY is set to a development/test default ('{admin_key[:12]}...'). "
            "Set a strong production key (e.g. openssl rand -hex 32)."
        )
    elif len(admin_key) < 16:
        errors.append("ADMIN_API_KEY is too short (must be at least 16 characters in production).")

    # 3. CSRF_SECRET check
    csrf_secret = (os.environ.get("CSRF_SECRET") or getattr(settings, "csrf_secret", "")).strip()
    if not csrf_secret or csrf_secret == "dev_csrf_secret_change_me_in_production":
        errors.append(
            "CSRF_SECRET must be set to a secure, random value in production. "
            "Generate one with: openssl rand -hex 32"
        )

    # 4. SESSION_SECRET check
    session_secret = (os.environ.get("SESSION_SECRET") or getattr(settings, "session_secret", "")).strip()
    if not session_secret or session_secret == "dev_session_secret_change_me_in_production":
        errors.append(
            "SESSION_SECRET must be set to a secure, random value in production. "
            "Generate one with: openssl rand -hex 32"
        )

    if errors:
        error_msg = (
            "🚨 CRITICAL CONFIGURATION ERROR: The application cannot start in production mode due to "
            f"insecure or missing security keys ({len(errors)} error(s)):\n"
            + "\n".join(f"  [{i+1}] {err}" for i, err in enumerate(errors))
        )
        logger.critical(error_msg)
        raise RuntimeError(error_msg)


def get_public_key() -> ed25519.Ed25519PublicKey:
    """Retrieve corresponding Ed25519 public key."""
    return get_signing_key().public_key()


def get_public_key_hex() -> str:
    """Retrieve public key as 64-character hex string."""
    return get_public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()


def create_demo_mandate(signing_key: ed25519.Ed25519PrivateKey) -> Mandate:
    """Construct and sign the standard demo mandate for hackathon evaluation."""
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=365)

    data = {
        "mandate_id": "demo_mandate_01",
        "owner_id": "user_demo_buyer",
        "agent_id": "agent_demo_01",
        "max_order_total": "1200.00",
        "auto_approve_under": "1000.00",
        "max_quantity": 1,
        "required_attributes": {
            "ram": "16GB",
            "storage": "512GB",
        },
        "allowed_domains": [
            "staples.com",
            "bestbuy.com",
            "newegg.com",
        ],
        "required_availability": "InStock",
        "daily_limit": "2500.00",
        "weekly_limit": "7500.00",
        "per_merchant_limit": "1500.00",
        "max_orders_per_hour": 10,
        "issued_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "nonce": "nonce_demo_bootstrap_01",
    }
    return sign_mandate(data, signing_key)


def create_monitor_mandate(signing_key: ed25519.Ed25519PrivateKey) -> Mandate:
    """
    Construct and sign a mandate for the second product category (Monitors).
    Proves Rule 2 is generic across non-laptop attribute schemas (screen_size, resolution, refresh_rate).
    """
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=365)

    data = {
        "mandate_id": "demo_monitor_mandate_01",
        "owner_id": "user_demo_buyer",
        "agent_id": "agent_monitor_01",
        "max_order_total": "600.00",
        "auto_approve_under": "550.00",
        "max_quantity": 1,
        "required_attributes": {
            "screen_size": "27 inch",
            "resolution": "4K UHD",
            "refresh_rate": "144Hz",
        },
        "allowed_domains": [
            "bestbuy.com",
            "staples.com",
            "newegg.com",
        ],
        "required_availability": "InStock",
        "daily_limit": "1500.00",
        "weekly_limit": "4000.00",
        "per_merchant_limit": "800.00",
        "max_orders_per_hour": 10,
        "issued_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "nonce": "nonce_monitor_bootstrap_01",
    }
    return sign_mandate(data, signing_key)


