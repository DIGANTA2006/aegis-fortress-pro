from datetime import datetime


class RuntimeHealthAggregator:
    def __init__(
        self,
        orchestrator_provider,
        market_state_store,
        kill_switch,
        database,
    ) -> None:
        self.orchestrator_provider = orchestrator_provider
        self.market_state_store = market_state_store
        self.kill_switch = kill_switch
        self.database = database

    def status(self) -> dict:
        orchestrator = self.orchestrator_provider()

        orchestrator_health = (
            orchestrator.health()
            if orchestrator is not None
            else {
                "running": False,
                "services": {},
            }
        )

        stale_market_keys = self.market_state_store.stale_keys()
        database_up = self.database.ping()
        kill_switch_status = self.kill_switch.status()

        healthy = (
            bool(orchestrator_health.get("running"))
            and database_up
            and not kill_switch_status.get("triggered", False)
        )

        return {
            "healthy": healthy,
            "captured_at": datetime.utcnow().isoformat(),
            "runtime": orchestrator_health,
            "database": {
                "up": database_up,
            },
            "market_data": {
                "stale_keys": stale_market_keys,
                "stale_count": len(stale_market_keys),
            },
            "kill_switch": kill_switch_status,
        }
