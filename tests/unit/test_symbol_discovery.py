from portfolio.symbol_discovery import discover_tradeable_symbols


class FakeExchange:
    def __init__(self):
        self.markets = {
            "AAA/USDT": {"active": True, "spot": True},
            "BBB/USDT": {"active": True, "spot": True},
            "USDC/USDT": {"active": True, "spot": True},
            "BADUP/USDT": {"active": True, "spot": True},
            "CCC/BTC": {"active": True, "spot": True},
        }

    def fetch_tickers(self, symbols=None):
        return {
            "AAA/USDT": {
                "last": 1.0,
                "bid": 0.999,
                "ask": 1.001,
                "quoteVolume": 3_000_000,
                "percentage": 3.0,
            },
            "BBB/USDT": {
                "last": 1.0,
                "bid": 0.90,
                "ask": 1.10,
                "quoteVolume": 10_000_000,
                "percentage": 4.0,
            },
            "USDC/USDT": {
                "last": 1.0,
                "bid": 0.9999,
                "ask": 1.0001,
                "quoteVolume": 100_000_000,
                "percentage": 0.01,
            },
            "BADUP/USDT": {
                "last": 1.0,
                "bid": 0.999,
                "ask": 1.001,
                "quoteVolume": 50_000_000,
                "percentage": 10.0,
            },
        }


class FakeWrapper:
    _ex = FakeExchange()


class FakeManager:
    primary = FakeWrapper()


def test_discovery_filters_stables_leveraged_and_wide_spread():
    symbols = discover_tradeable_symbols(
        FakeManager(),
        max_symbols=3,
        min_quote_volume=1_000_000,
        min_change_pct=0.0,
        max_spread_bps=30.0,
        fallback_symbols=("DOGE/USDT",),
    )

    assert symbols == ("AAA/USDT",)
