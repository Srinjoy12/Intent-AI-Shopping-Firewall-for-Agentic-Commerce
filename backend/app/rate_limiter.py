"""Intent Gateway — Rate limiting and circuit breaker for public demo protection."""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class DailyCounter:
    """Simple daily counter that resets at midnight (approximate)."""

    channel3_calls: int = 0
    llm_calls: int = 0
    reset_date: str = ""

    def _check_reset(self):
        today = time.strftime("%Y-%m-%d")
        if self.reset_date != today:
            self.channel3_calls = 0
            self.llm_calls = 0
            self.reset_date = today

    def increment_channel3(self) -> bool:
        """Increment Channel3 call count. Returns True if within budget."""
        self._check_reset()
        settings = get_settings()
        if self.channel3_calls >= settings.global_channel3_daily_cap:
            logger.warning(
                "Channel3 daily cap reached (%d/%d)",
                self.channel3_calls,
                settings.global_channel3_daily_cap,
            )
            return False
        self.channel3_calls += 1
        return True

    def increment_llm(self) -> bool:
        """Increment LLM call count. Returns True if within budget."""
        self._check_reset()
        settings = get_settings()
        if self.llm_calls >= settings.global_llm_daily_cap:
            logger.warning(
                "LLM daily cap reached (%d/%d)",
                self.llm_calls,
                settings.global_llm_daily_cap,
            )
            return False
        self.llm_calls += 1
        return True

    def get_status(self) -> dict:
        self._check_reset()
        settings = get_settings()
        return {
            "channel3_calls_today": self.channel3_calls,
            "channel3_daily_cap": settings.global_channel3_daily_cap,
            "llm_calls_today": self.llm_calls,
            "llm_daily_cap": settings.global_llm_daily_cap,
            "circuit_breaker_tripped": (
                self.channel3_calls >= settings.global_channel3_daily_cap
                or self.llm_calls >= settings.global_llm_daily_cap
            ),
        }


# Global singleton
daily_counter = DailyCounter()
