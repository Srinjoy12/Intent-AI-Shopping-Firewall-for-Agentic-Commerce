"""
Intent Gateway — Production Persistence, Key Management & Startup Verification Tests.

Verifies:
1. Production mode refuses startup if MANDATE_SIGNING_KEY, ADMIN_API_KEY, CSRF_SECRET,
   or SESSION_SECRET are missing or left at dev defaults.
2. Development mode allows ephemeral key generation with warning and reports key_source: "generated".
3. Environment-provided signing key reports key_source: "env".
4. GET /api/health returns key_source, database_type, persistent_storage, worker_count,
   and leaks zero secret keys or private data.
5. Storage persistence detection correctly identifies ephemeral (/tmp) vs persistent storage.
6. Startup audit chain self-check verifies the audit ledger.
7. Concurrency warnings for SQLite when WEB_CONCURRENCY > 1.
"""

import os
import sys
import secrets
import logging
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport

from app.config import Settings
from app.mandate import (
    validate_production_configuration,
    get_signing_key,
    get_key_source,
    _DEV_KEY,
)
from app.db import (
    get_db_path,
    get_database_type,
    is_persistent_storage,
    init_db,
    DB_PATH,
)
from app.audit import append_audit_event, verify_audit_chain
from app.main import app, lifespan


# ── Production Mode Validation Tests ─────────────────────────────────────────

def test_production_refuses_missing_mandate_signing_key():
    """In production mode, missing MANDATE_SIGNING_KEY must raise RuntimeError."""
    mock_settings = Settings(
        app_env="production",
        mandate_signing_key="",
        admin_api_key="production_secure_admin_key_1234567890",
        csrf_secret="production_secure_csrf_secret_1234567890",
        session_secret="production_secure_session_secret_1234567890",
    )
    with patch.dict(os.environ, {"APP_ENV": "production", "MANDATE_SIGNING_KEY": ""}):
        with pytest.raises(RuntimeError) as exc_info:
            validate_production_configuration(mock_settings)
        assert "MANDATE_SIGNING_KEY is missing" in str(exc_info.value)


def test_production_refuses_dev_default_mandate_signing_key():
    """In production mode, placeholder or all-zeros MANDATE_SIGNING_KEY must raise RuntimeError."""
    mock_settings = Settings(
        app_env="production",
        mandate_signing_key="0" * 64,
        admin_api_key="production_secure_admin_key_1234567890",
        csrf_secret="production_secure_csrf_secret_1234567890",
        session_secret="production_secure_session_secret_1234567890",
    )
    with patch.dict(os.environ, {"APP_ENV": "production", "MANDATE_SIGNING_KEY": "0" * 64}):
        with pytest.raises(RuntimeError) as exc_info:
            validate_production_configuration(mock_settings)
        assert "insecure default/placeholder" in str(exc_info.value)


def test_production_refuses_invalid_hex_mandate_signing_key():
    """In production mode, non-hex or invalid-length MANDATE_SIGNING_KEY must raise RuntimeError."""
    mock_settings = Settings(
        app_env="production",
        mandate_signing_key="not_valid_hex_key_at_all",
        admin_api_key="production_secure_admin_key_1234567890",
        csrf_secret="production_secure_csrf_secret_1234567890",
        session_secret="production_secure_session_secret_1234567890",
    )
    with patch.dict(os.environ, {"APP_ENV": "production", "MANDATE_SIGNING_KEY": "not_valid_hex_key_at_all"}):
        with pytest.raises(RuntimeError) as exc_info:
            validate_production_configuration(mock_settings)
        assert "valid 64-character hexadecimal" in str(exc_info.value) or "must be exactly 32 bytes" in str(exc_info.value)


def test_production_refuses_missing_or_dev_default_admin_api_key():
    """In production mode, default or dev ADMIN_API_KEY must raise RuntimeError."""
    valid_key = secrets.token_hex(32)
    mock_settings = Settings(
        app_env="production",
        mandate_signing_key=valid_key,
        admin_api_key="admin_super_secret_test_key",  # Dev default
        csrf_secret="production_secure_csrf_secret_1234567890",
        session_secret="production_secure_session_secret_1234567890",
    )
    with patch.dict(os.environ, {"APP_ENV": "production", "ADMIN_API_KEY": "admin_super_secret_test_key"}):
        with pytest.raises(RuntimeError) as exc_info:
            validate_production_configuration(mock_settings)
        assert "ADMIN_API_KEY is set to a development/test default" in str(exc_info.value)


def test_production_refuses_dev_csrf_and_session_secrets():
    """In production mode, default CSRF_SECRET and SESSION_SECRET must raise RuntimeError."""
    valid_key = secrets.token_hex(32)
    mock_settings = Settings(
        app_env="production",
        mandate_signing_key=valid_key,
        admin_api_key="production_secure_admin_key_1234567890",
        csrf_secret="dev_csrf_secret_change_me_in_production",
        session_secret="dev_session_secret_change_me_in_production",
    )
    with patch.dict(os.environ, {
        "APP_ENV": "production",
        "CSRF_SECRET": "dev_csrf_secret_change_me_in_production",
        "SESSION_SECRET": "dev_session_secret_change_me_in_production",
    }):
        with pytest.raises(RuntimeError) as exc_info:
            validate_production_configuration(mock_settings)
        assert "CSRF_SECRET must be set to a secure" in str(exc_info.value)
        assert "SESSION_SECRET must be set to a secure" in str(exc_info.value)


def test_production_passes_with_strong_keys():
    """In production mode with proper keys, validation must pass without exception."""
    valid_mandate_key = secrets.token_hex(32)
    mock_settings = Settings(
        app_env="production",
        mandate_signing_key=valid_mandate_key,
        admin_api_key="prod_admin_key_super_secure_9876543210",
        csrf_secret="prod_csrf_secret_super_secure_9876543210",
        session_secret="prod_session_secret_super_secure_9876543210",
    )
    with patch.dict(os.environ, {
        "APP_ENV": "production",
        "MANDATE_SIGNING_KEY": valid_mandate_key,
        "ADMIN_API_KEY": "prod_admin_key_super_secure_9876543210",
        "CSRF_SECRET": "prod_csrf_secret_super_secure_9876543210",
        "SESSION_SECRET": "prod_session_secret_super_secure_9876543210",
    }):
        # Should not raise any error
        validate_production_configuration(mock_settings)


# ── Key Source Reporting Tests ───────────────────────────────────────────────

def test_dev_mode_ephemeral_key_source(caplog):
    """In dev mode without env key, key_source must report 'generated' and log warning."""
    import app.mandate as mandate_module
    mandate_module._DEV_KEY = None
    mandate_module._KEY_SOURCE = "generated"

    with patch.dict(os.environ, {"MANDATE_SIGNING_KEY": ""}):
        with caplog.at_level(logging.WARNING):
            key = mandate_module.get_signing_key()
            source = mandate_module.get_key_source()
            assert key is not None
            assert source == "generated"
            assert "MANDATE_SIGNING_KEY not configured in environment" in caplog.text


def test_configured_env_key_source():
    """When MANDATE_SIGNING_KEY is provided in env, key_source must report 'env'."""
    import app.mandate as mandate_module
    sample_key = secrets.token_hex(32)
    with patch.dict(os.environ, {"MANDATE_SIGNING_KEY": sample_key}):
        key = mandate_module.get_signing_key()
        source = mandate_module.get_key_source()
        assert key is not None
        assert source == "env"


# ── Health Endpoint Telemetry & Secret Leak Protection ───────────────────────

@pytest.mark.asyncio
async def test_health_endpoint_telemetry_and_no_secrets():
    """GET /api/health reports key_source, database_type, persistent_storage, worker_count, without leaking secrets."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()

        # Telemetry fields must be present
        assert "status" in data
        assert data["status"] == "ok"
        assert "key_source" in data
        assert data["key_source"] in ("env", "generated")
        assert "database_type" in data
        assert data["database_type"] in ("sqlite", "postgresql")
        assert "persistent_storage" in data
        assert isinstance(data["persistent_storage"], bool)
        assert "worker_count" in data
        assert isinstance(data["worker_count"], int)
        assert "app_env" in data
        assert "app_mode" in data

        # STRICT ASSERTION: Absolutely no secret values or sensitive tokens in payload
        forbidden_substrings = [
            "signing_key",
            "private_key",
            "admin_api_key",
            "csrf_secret",
            "session_secret",
            "paypal_client_secret",
            "channel3_api_key",
        ]
        raw_json_str = response.text.lower()
        for forbidden in forbidden_substrings:
            assert forbidden not in raw_json_str, f"Leaked sensitive field '{forbidden}' in /api/health!"


# ── Storage Persistence & Detection Tests ────────────────────────────────────

def test_storage_persistence_detection():
    """Detects ephemeral /tmp vs persistent storage paths."""
    # Ephemeral cases
    with patch.dict(os.environ, {"DATABASE_PATH": "/tmp/test.db"}):
        assert not is_persistent_storage()

    with patch.dict(os.environ, {"DATABASE_PATH": ":memory:"}):
        assert not is_persistent_storage()

    with patch.dict(os.environ, {"DATABASE_PATH": "/dev/shm/cache.db"}):
        assert not is_persistent_storage()

    # Explicit persistent cases
    with patch.dict(os.environ, {"DATABASE_PATH": "/var/data/intent.db"}):
        assert is_persistent_storage()

    with patch.dict(os.environ, {"RENDER_DISK_NAME": "intent-persistent-disk"}):
        assert is_persistent_storage()


def test_database_type_detection():
    """Detects database engine type from URL."""
    with patch.dict(os.environ, {"DATABASE_URL": "postgresql://usr:pwd@localhost/db"}):
        assert get_database_type() == "postgresql"

    with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///tmp/test.db"}):
        assert get_database_type() == "sqlite"


# ── Startup Concurrency Warning & Audit Self-Check Tests ─────────────────────

@pytest.mark.asyncio
async def test_startup_audit_chain_self_check_runs():
    """At startup, verify_audit_chain runs and verifies the historical audit ledger."""
    # Seed an audit event to make sure chain has items
    await append_audit_event("TEST_STARTUP_CHECK", {"purpose": "verification"})
    result = await verify_audit_chain()
    assert result["valid"] is True
    assert result["events_checked"] >= 1
    assert "authentic" in result["message"] or "intact" in result["message"] or "verified" in result["message"]


@pytest.mark.asyncio
async def test_startup_concurrency_warning(caplog):
    """When WEB_CONCURRENCY > 1 with SQLite, a concurrency warning is logged during lifespan."""
    with patch.dict(os.environ, {"WEB_CONCURRENCY": "4", "DATABASE_URL": "sqlite:///tmp/test.db"}):
        with caplog.at_level(logging.WARNING):
            async with lifespan(app):
                pass
            assert "CONCURRENCY WARNING" in caplog.text
            assert "WEB_CONCURRENCY=4 > 1 with SQLite" in caplog.text
