from feeds.market_data_normalizer import MarketDataNormalizer


def test_ticker_normalization():
    normalizer = MarketDataNormalizer()

    tick = normalizer.normalize_ticker(
        exchange="SIM",
        symbol="BTC/USDT",
        payload={
            "bid": 100.0,
            "ask": 101.0,
            "last": 100.5,
            "baseVolume": 10.0,
        },
    )

    assert tick.symbol == "BTC/USDT"
    assert tick.bid == 100.0
    assert tick.ask == 101.0
    assert tick.last == 100.5
    assert tick.mid_price == 100.5
    assert tick.spread == 1.0


def test_orderbook_normalization():
    normalizer = MarketDataNormalizer()

    orderbook = normalizer.normalize_orderbook(
        exchange="SIM",
        symbol="BTC/USDT",
        payload={
            "bids": [
                [100.0, 2.0],
                [99.0, 1.0],
            ],
            "asks": [
                [101.0, 3.0],
                [102.0, 1.0],
            ],
        },
        depth=10,
    )

    assert orderbook.best_bid == 100.0
    assert orderbook.best_ask == 101.0
    assert orderbook.spread == 1.0
    assert orderbook.bid_depth == 3.0
    assert orderbook.ask_depth == 4.0
