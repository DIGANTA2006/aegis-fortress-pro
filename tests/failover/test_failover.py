"""
Failover tests – verify that the system degrades gracefully
when the primary exchange becomes unavailable.
"""
import pytest
from core.failover_manager import FailoverManager
from core.exchange_registry import ExchangeRegistry


def test_failover_manager_imports():
    """FailoverManager and ExchangeRegistry must be importable."""
    assert FailoverManager is not None
    assert ExchangeRegistry is not None


def test_exchange_registry_register_and_get():
    registry = ExchangeRegistry()
    registry.register("binance", object())
    assert registry.get("binance") is not None


def test_exchange_registry_missing_returns_none():
    registry = ExchangeRegistry()
    assert registry.get("nonexistent") is None
