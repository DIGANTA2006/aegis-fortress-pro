#Requires -Version 5.1
<#
.SYNOPSIS
    Fix 01 " Wire microservices to real subsystems.

.DESCRIPTION
    Replaces the three print-only stubs in microservices/ with real
    implementations that call the actual Aegis subsystems:
      - ExecutionService  ' polls an asyncio.Queue for Order objects,
                            runs them through ExecutionGateway
      - MarketDataService ' calls ExchangeManager to stream OHLCV ticks
                            and publishes MarketEvents onto the EventBus
      - RiskService       ' runs periodic risk checks via RiskManager,
                            fires the KillSwitch if limits are breached

.PARAMETER ProjectRoot
    Path to the aegis_v2 directory.  Defaults to .\aegis_v2 next to this script.
#>

param(
    [string]$ProjectRoot = $PSScriptRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function P([string]$rel) { Join-Path $ProjectRoot $rel }
function Write-Step([string]$msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK([string]$msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function WriteFile([string]$rel, [string]$content) {
    $full = P $rel
    [System.IO.File]::WriteAllText($full, $content, [System.Text.UTF8Encoding]::new($false))
    Write-OK $rel
}

if (-not (Test-Path $ProjectRoot)) { Write-Error "Project root not found: $ProjectRoot"; exit 1 }
Write-Host "Project root: $ProjectRoot" -ForegroundColor Yellow

# """""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
# 1. microservices/execution_service.py
# """""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
Write-Step "microservices/execution_service.py"

WriteFile "microservices\execution_service.py" @'
"""
microservices/execution_service.py  -  AEGIS PRO v2

Consumes Order objects from an asyncio.Queue and routes them through
ExecutionGateway.  The gateway handles validation, smart-order-routing,
state-machine transitions, and exchange submission.

Usage
-----
    queue = asyncio.Queue()
    svc   = ExecutionService(order_queue=queue, router=smart_order_router)
    await svc.start()          # blocks; run as an asyncio task
"""

import asyncio
import logging

from microservices.base_service import BaseService
from execution.execution_gateway import ExecutionGateway

log = logging.getLogger(__name__)


class ExecutionService(BaseService):
    """
    Async worker that drains an order queue and submits each order
    to the ExecutionGateway.

    Parameters
    ----------
    order_queue : asyncio.Queue
        Producer puts Order objects here; this service consumes them.
    router : SmartOrderRouter
        Passed straight through to ExecutionGateway so it can pick
        the best exchange for each order.
    poll_interval : float
        Seconds to sleep when the queue is empty (avoids busy-wait).
    """

    def __init__(
        self,
        order_queue: asyncio.Queue,
        router,
        poll_interval: float = 0.1,
    ):
        super().__init__("execution-service")
        self.order_queue   = order_queue
        self.poll_interval = poll_interval
        self.gateway       = ExecutionGateway(router=router)
        self._processed    = 0
        self._failed       = 0

    # ------------------------------------------------------------------
    # BaseService interface
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Drain the order queue until the service is stopped."""
        log.info("ExecutionService: waiting for orders")

        while self.running:
            try:
                order = self.order_queue.get_nowait()
            except asyncio.QueueEmpty:
                await asyncio.sleep(self.poll_interval)
                continue

            try:
                result = await self.gateway.execute(order)
                self._processed += 1
                log.info(
                    "Order executed | id=%s status=%s exchange=%s",
                    result.correlation_id,
                    result.status,
                    result.exchange,
                )
            except Exception:
                self._failed += 1
                log.exception("ExecutionService: unhandled error for order %s", order.correlation_id)
            finally:
                self.order_queue.task_done()

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        return {
            "processed": self._processed,
            "failed":    self._failed,
            "queue_size": self.order_queue.qsize(),
        }
'@

# """""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
# 2. microservices/market_data_service.py
# """""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
Write-Step "microservices/market_data_service.py"

WriteFile "microservices\market_data_service.py" @'
"""
microservices/market_data_service.py  -  AEGIS PRO v2

Streams OHLCV candles from ExchangeManager and publishes MarketEvent
objects onto the EventBus so every subscriber (risk, execution, ML)
stays in sync without polling the exchange directly.

Usage
-----
    svc = MarketDataService(
        exchange_manager = exchange_mgr,
        event_bus        = bus,
        symbols          = ["BTC/USDT", "ETH/USDT"],
        timeframe        = "1m",
        poll_interval    = 60,
    )
    await svc.start()
"""

import asyncio
import logging
import time

from microservices.base_service import BaseService
from core.events.market_event import MarketEvent

log = logging.getLogger(__name__)


class MarketDataService(BaseService):
    """
    Periodically fetches the latest closed OHLCV candle for each symbol
    and publishes a MarketEvent onto the shared EventBus.

    Parameters
    ----------
    exchange_manager : ExchangeManager
        Provides ``fetch_ohlcv(symbol, timeframe, limit)`` calls.
    event_bus : EventBus
        Subscribers call ``event_bus.subscribe("market", handler)``.
    symbols : list[str]
        E.g. ``["BTC/USDT", "ETH/USDT"]``.
    timeframe : str
        CCXT timeframe string, e.g. ``"1m"``, ``"15m"``.
    poll_interval : float
        Seconds between fetch rounds (should match the candle duration).
    """

    def __init__(
        self,
        exchange_manager,
        event_bus,
        symbols: list[str],
        timeframe: str = "1m",
        poll_interval: float = 60.0,
    ):
        super().__init__("market-data-service")
        self.exchange_manager = exchange_manager
        self.event_bus        = event_bus
        self.symbols          = symbols
        self.timeframe        = timeframe
        self.poll_interval    = poll_interval
        self._tick_count      = 0

    # ------------------------------------------------------------------
    # BaseService interface
    # ------------------------------------------------------------------

    async def run(self) -> None:
        log.info(
            "MarketDataService: streaming %d symbol(s) on %s",
            len(self.symbols),
            self.timeframe,
        )

        while self.running:
            start = time.monotonic()

            for symbol in self.symbols:
                try:
                    await self._fetch_and_publish(symbol)
                except Exception:
                    log.exception("MarketDataService: fetch failed for %s", symbol)

            elapsed = time.monotonic() - start
            sleep   = max(0.0, self.poll_interval - elapsed)
            await asyncio.sleep(sleep)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_and_publish(self, symbol: str) -> None:
        """Fetch the latest candle and emit a MarketEvent."""
        # fetch_ohlcv returns list of [ts, open, high, low, close, volume]
        candles = await asyncio.to_thread(
            self.exchange_manager.fetch_ohlcv,
            symbol,
            self.timeframe,
            2,           # fetch 2 so we use the last *closed* candle [0]
        )
        if not candles:
            log.warning("MarketDataService: no candles for %s", symbol)
            return

        ts, open_, high, low, close, volume = candles[0]

        event = MarketEvent(
            event_type="market",
            symbol=symbol,
            price=close,
            volume=volume,
            exchange=self.exchange_manager.primary_id,
        )
        await self.event_bus.emit("market", event)
        self._tick_count += 1

        log.debug(
            "MarketEvent | symbol=%s close=%.4f vol=%.2f ticks=%d",
            symbol, close, volume, self._tick_count,
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        return {"tick_count": self._tick_count, "symbols": self.symbols}
'@

# """""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
# 3. microservices/risk_service.py
# """""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
Write-Step "microservices/risk_service.py"

WriteFile "microservices\risk_service.py" @'
"""
microservices/risk_service.py  -  AEGIS PRO v2

Runs periodic risk checks via RiskManager and fires the KillSwitch
if any hard limit is breached.  Also listens for MarketEvents on the
EventBus so it can update ATR / volatility state in near-real-time.

Usage
-----
    svc = RiskService(
        risk_manager    = risk_mgr,
        kill_switch     = ks,
        event_bus       = bus,
        check_interval  = 5.0,
    )
    await svc.start()
"""

import asyncio
import logging
import time

from microservices.base_service import BaseService

log = logging.getLogger(__name__)


class RiskService(BaseService):
    """
    Periodic risk-monitor that sits between the EventBus and the
    RiskManager / KillSwitch.

    Parameters
    ----------
    risk_manager : RiskManager
        Provides ``check_drawdown()``, ``check_daily_loss()``, etc.
    kill_switch : KillSwitch
        Called when a hard risk limit is breached.
    event_bus : EventBus
        The service subscribes to ``"market"`` events so RiskManager
        can stay updated with latest prices without polling.
    check_interval : float
        Seconds between active risk checks (default 5 s).
    """

    def __init__(
        self,
        risk_manager,
        kill_switch,
        event_bus,
        check_interval: float = 5.0,
    ):
        super().__init__("risk-service")
        self.risk_manager    = risk_manager
        self.kill_switch     = kill_switch
        self.event_bus       = event_bus
        self.check_interval  = check_interval
        self._checks_run     = 0
        self._breaches       = 0
        self._last_check: float = 0.0

        # Subscribe to market events so risk state stays current
        event_bus.subscribe("market", self._on_market_event)

    # ------------------------------------------------------------------
    # BaseService interface
    # ------------------------------------------------------------------

    async def run(self) -> None:
        log.info("RiskService: monitoring active (interval=%.1fs)", self.check_interval)

        while self.running:
            now = time.monotonic()
            if now - self._last_check >= self.check_interval:
                await self._run_checks()
                self._last_check = now
            await asyncio.sleep(0.5)   # tight loop so we don't lag behind

    # ------------------------------------------------------------------
    # Risk checks
    # ------------------------------------------------------------------

    async def _run_checks(self) -> None:
        self._checks_run += 1
        try:
            breached, reason = self._evaluate_limits()
            if breached:
                self._breaches += 1
                log.critical("RiskService: limit breached " %s " activating kill switch", reason)
                await asyncio.to_thread(self.kill_switch.trigger, reason)
            else:
                log.debug("RiskService: check #%d passed", self._checks_run)
        except Exception:
            log.exception("RiskService: error during risk check")

    def _evaluate_limits(self) -> tuple[bool, str]:
        """
        Call each RiskManager guard in priority order.
        Returns (breached: bool, reason: str).
        """
        checks = [
            ("check_drawdown",    "max drawdown exceeded"),
            ("check_daily_loss",  "daily loss limit hit"),
            ("check_position_size", "position size limit exceeded"),
        ]
        for method, label in checks:
            fn = getattr(self.risk_manager, method, None)
            if fn is None:
                continue
            try:
                if not fn():           # False ' limit breached
                    return True, label
            except Exception:
                log.exception("RiskService: %s raised", method)
        return False, ""

    # ------------------------------------------------------------------
    # Event handler
    # ------------------------------------------------------------------

    def _on_market_event(self, event) -> None:
        """Update RiskManager price state whenever a new tick arrives."""
        try:
            update_fn = getattr(self.risk_manager, "update_market_price", None)
            if update_fn:
                update_fn(event.symbol, event.price)
        except Exception:
            log.exception("RiskService: _on_market_event failed")

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        return {
            "checks_run": self._checks_run,
            "breaches":   self._breaches,
        }
'@

# """""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
# Done
# """""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
Write-Host "`n=================================================" -ForegroundColor Magenta
Write-Host "  Fix 01 complete - microservices wired." -ForegroundColor Magenta
Write-Host "  Next: run Fix02_IntegrationTests.ps1" -ForegroundColor Magenta
Write-Host "=================================================" -ForegroundColor Magenta
