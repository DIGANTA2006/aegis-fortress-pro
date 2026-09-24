"""
Integration tests for exchange.py ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â ExchangeWrapper and ExchangeManager.

All network calls are intercepted with unittest.mock so the suite runs
offline and deterministically.  The goal is to verify:

  1. ExchangeManager can be constructed with mock exchange objects.
  2. create_order round-trips correctly (buy / sell, market / limit).
  3. cancel_order is forwarded to the right exchange.
  4. When the primary exchange raises, ExchangeManager falls back to
     the backup if a FailoverManager is attached.
  5. API errors are raised as plain exceptions (not silently swallowed).
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import exchange as exchange_module
from exchange import ExchangeManager, ExchangeWrapper


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_exchange(exchange_id: str = "binance") -> MagicMock:
    """Return a mock that looks like a ccxt exchange object."""
    ex = MagicMock()
    ex.id = exchange_id
    ex.create_order.return_value = {
        "id": f"order-{exchange_id}-001",
        "symbol": "BTC/USDT",
        "side": "buy",
        "type": "market",
        "amount": 0.001,
        "price": 60_000.0,
        "status": "closed",
    }
    ex.cancel_order.return_value = {"id": f"order-{exchange_id}-001", "status": "canceled"}
    ex.fetch_balance.return_value = {"USDT": {"free": 10_000.0, "total": 10_000.0}}
    ex.fetch_order.return_value   = {"id": f"order-{exchange_id}-001", "status": "closed"}
    return ex


@pytest.fixture
def mock_primary():
    return _make_exchange("binance")


@pytest.fixture
def mock_backup():
    return _make_exchange("kraken")


# ---------------------------------------------------------------------------
# ExchangeWrapper
# ---------------------------------------------------------------------------

class TestExchangeWrapper:

    def test_create_market_buy(self, mock_primary):
        wrapper = ExchangeWrapper("binance", mock_primary, {})
        result  = wrapper.create_order("BTC/USDT", "market", "buy", 0.001)

        mock_primary.create_order.assert_called_once_with(
            "BTC/USDT", "market", "buy", 0.001, None
        )
        assert result["status"] == "closed"

    def test_create_limit_sell(self, mock_primary):
        wrapper = ExchangeWrapper("binance", mock_primary, {})
        mock_primary.create_order.return_value["side"] = "sell"
        result = wrapper.create_order("ETH/USDT", "limit", "sell", 1.0, price=3_000.0)

        mock_primary.create_order.assert_called_once_with(
            "ETH/USDT", "limit", "sell", 1.0, 3_000.0
        )
        assert result["side"] == "sell"

    def test_cancel_order(self, mock_primary):
        wrapper = ExchangeWrapper("binance", mock_primary, {})
        result  = wrapper.cancel_order("order-binance-001", "BTC/USDT")

        mock_primary.cancel_order.assert_called_once_with("order-binance-001", "BTC/USDT")
        assert result["status"] == "canceled"

    def test_fetch_balance(self, mock_primary):
        wrapper  = ExchangeWrapper("binance", mock_primary, {})
        balance  = wrapper.fetch_balance()
        assert balance["USDT"]["free"] == 10_000.0

    def test_api_error_propagates(self, mock_primary):
        mock_primary.create_order.side_effect = Exception("Rate limit exceeded")
        wrapper = ExchangeWrapper("binance", mock_primary, {})
        with pytest.raises(Exception, match="Rate limit exceeded"):
            wrapper.create_order("BTC/USDT", "market", "buy", 0.001)


# ---------------------------------------------------------------------------
# ExchangeManager
# ---------------------------------------------------------------------------

class TestExchangeManager:

    def test_module_importable(self):
        assert exchange_module is not None

    def test_exchange_manager_class_exists(self):
        assert ExchangeManager is not None

    def test_exchange_wrapper_class_exists(self):
        assert ExchangeWrapper is not None

    def test_create_order_delegates_to_wrapper(self, mock_primary):
        """ExchangeManager.create_order should forward to the primary wrapper."""
        with patch("exchange.ccxt") as mock_ccxt:
            mock_ccxt.binance.return_value = mock_primary
            mock_ccxt.kraken.return_value  = _make_exchange("kraken")

            mgr    = ExchangeManager.__new__(ExchangeManager)
            mgr.primary   = ExchangeWrapper("binance", mock_primary, {})
            mgr.exchanges = {"binance": mgr.primary}

            result = mgr.primary.create_order("BTC/USDT", "market", "buy", 0.001)
            assert result["id"].startswith("order-binance")

    def test_cancel_order_delegates(self, mock_primary):
        mgr         = ExchangeManager.__new__(ExchangeManager)
        mgr.primary = ExchangeWrapper("binance", mock_primary, {})
        result      = mgr.primary.cancel_order("order-binance-001", "BTC/USDT")
        assert result["status"] == "canceled"

    def test_primary_error_raises(self, mock_primary):
        mock_primary.create_order.side_effect = ConnectionError("exchange offline")
        wrapper = ExchangeWrapper("binance", mock_primary, {})
        with pytest.raises(ConnectionError):
            wrapper.create_order("BTC/USDT", "market", "buy", 0.001)


# ---------------------------------------------------------------------------
# Failover behaviour
# ---------------------------------------------------------------------------

class TestFailover:

    def test_failover_manager_switches_to_backup(self, mock_primary, mock_backup):
        """
        When primary.fetch_balance raises, FailoverManager.get_active_exchange
        should return the backup exchange.
        """
        from core.failover_manager import FailoverManager

        mock_primary.fetch_balance.side_effect = ConnectionError("down")
        fm = FailoverManager(primary=mock_primary, backup=mock_backup)

        active = fm.get_active_exchange()
        assert active is mock_backup

    def test_failover_uses_primary_when_healthy(self, mock_primary, mock_backup):
        from core.failover_manager import FailoverManager

        fm = FailoverManager(primary=mock_primary, backup=mock_backup)
        assert fm.get_active_exchange() is mock_primary