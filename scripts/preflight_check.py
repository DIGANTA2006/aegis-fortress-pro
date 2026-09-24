from __future__ import annotations

import importlib
import json
import os
import socket
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    severity: str = "ERROR"


class PreflightChecker:
    def __init__(self) -> None:
        self.results: list[CheckResult] = []

    def run(self) -> int:
        self.check_python_version()
        self.check_project_directories()
        self.check_critical_imports()
        self.check_runtime_settings()
        self.check_runtime_container_build()
        self.check_port_available("health", self._env_str("AEGIS_HEALTH_HOST", "127.0.0.1"), self._env_int("AEGIS_HEALTH_PORT", 8080))
        self.check_port_available("metrics", "127.0.0.1", self._env_int("AEGIS_METRICS_PORT", 9000))
        self.check_writable_path("logs")
        self.check_writable_path("data")

        self.print_report()

        failures = [
            result
            for result in self.results
            if not result.passed and result.severity == "ERROR"
        ]

        return 1 if failures else 0

    def add(
        self,
        name: str,
        passed: bool,
        message: str,
        severity: str = "ERROR",
    ) -> None:
        self.results.append(
            CheckResult(
                name=name,
                passed=passed,
                message=message,
                severity=severity,
            )
        )

    def check_python_version(self) -> None:
        passed = sys.version_info >= (3, 10)

        self.add(
            "python_version",
            passed,
            (
                f"Python {sys.version.split()[0]} detected"
                if passed
                else f"Python >= 3.10 required, found {sys.version.split()[0]}"
            ),
        )

    def check_project_directories(self) -> None:
        required = [
            "app",
            "core",
            "execution",
            "feeds",
            "microservices",
            "models",
            "portfolio",
            "risk",
            "monitoring",
            "backtesting",
            "tests",
        ]

        missing = [
            directory
            for directory in required
            if not Path(directory).exists()
        ]

        self.add(
            "project_directories",
            len(missing) == 0,
            "All required project folders exist"
            if not missing
            else f"Missing folders: {missing}",
        )

    def check_critical_imports(self) -> None:
        modules = [
            "app.runtime_container",
            "app.runtime_settings",
            "core.event_bus",
            "core.database_manager",
            "execution.execution_pipeline",
            "feeds.market_data_normalizer",
            "monitoring.runtime_metrics",
            "monitoring.runtime_health",
            "backtesting.backtest_runtime",
        ]

        failed: list[str] = []

        for module in modules:
            try:
                importlib.import_module(module)
            except Exception as exc:
                failed.append(f"{module}: {exc}")

        self.add(
            "critical_imports",
            len(failed) == 0,
            "Critical modules import successfully"
            if not failed
            else "Import failures: " + " | ".join(failed),
        )

    def check_runtime_settings(self) -> None:
        try:
            from config import load_config, validate_config
            from app.runtime_settings import RuntimeSettings

            cfg = load_config()
            errors = validate_config(cfg)

            if errors:
                self.add(
                    "config_validation",
                    False,
                    "Config validation failed: " + " | ".join(errors),
                )
                return

            settings = RuntimeSettings.from_config(cfg)
            settings.validate()

            if not settings.market_symbols:
                self.add(
                    "runtime_settings",
                    False,
                    "No market symbols configured. Set AEGIS_MARKET_SYMBOLS.",
                )
                return

            self.add(
                "runtime_settings",
                True,
                f"Runtime settings valid. Symbols={settings.market_symbols}",
            )

        except Exception as exc:
            self.add(
                "runtime_settings",
                False,
                f"Runtime settings check failed: {exc}",
            )

    def check_runtime_container_build(self) -> None:
        try:
            from app.runtime_container import RuntimeContainer

            RuntimeContainer.build()

            self.add(
                "runtime_container_build",
                True,
                "RuntimeContainer builds successfully",
            )

        except Exception as exc:
            self.add(
                "runtime_container_build",
                False,
                f"RuntimeContainer build failed: {exc}",
            )

    def check_port_available(
        self,
        label: str,
        host: str,
        port: int,
    ) -> None:
        bind_host = host

        if host == "0.0.0.0":
            bind_host = "0.0.0.0"

        sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM,
        )

        try:
            sock.bind((bind_host, port))

            self.add(
                f"{label}_port",
                True,
                f"Port available: {host}:{port}",
            )

        except OSError as exc:
            self.add(
                f"{label}_port",
                False,
                f"Port unavailable: {host}:{port} ({exc})",
            )

        finally:
            sock.close()

    def check_writable_path(
        self,
        directory: str,
    ) -> None:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)

        try:
            with tempfile.NamedTemporaryFile(
                dir=str(path),
                delete=True,
            ):
                pass

            self.add(
                f"{directory}_writable",
                True,
                f"Directory writable: {directory}",
            )

        except Exception as exc:
            self.add(
                f"{directory}_writable",
                False,
                f"Directory not writable: {directory} ({exc})",
            )

    def print_report(self) -> None:
        payload = {
            "passed": all(
                result.passed or result.severity != "ERROR"
                for result in self.results
            ),
            "checks": [
                asdict(result)
                for result in self.results
            ],
        }

        print(
            json.dumps(
                payload,
                indent=2,
            )
        )

    def _env_int(
        self,
        name: str,
        default: int,
    ) -> int:
        raw = os.environ.get(name)

        if raw is None or raw == "":
            return default

        return int(raw)

    def _env_str(
        self,
        name: str,
        default: str,
    ) -> str:
        raw = os.environ.get(name)

        return raw if raw else default


def main() -> None:
    checker = PreflightChecker()
    raise SystemExit(
        checker.run()
    )


if __name__ == "__main__":
    main()