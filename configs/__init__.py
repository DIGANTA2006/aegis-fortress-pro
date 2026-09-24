"""
configs package  -  AEGIS PRO v2

Provides load_yaml_config() which reads configs/default.yaml and
merges it with environment-variable overrides.

The result is a plain nested dict Ã¢â‚¬â€ no external dependencies required
(falls back gracefully when PyYAML is not installed).

Usage
-----
    from configs import load_yaml_config
    cfg = load_yaml_config()
    port = cfg["monitoring"]["metrics_port"]   # -> 9090
"""

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULT_YAML = Path(__file__).parent / "default.yaml"


def load_yaml_config(path: str | Path) -> dict:
    """
    Load YAML configuration and apply AEGIS_* environment overrides.

    Supported rules:
    - Missing YAML path returns an empty dictionary.
    - Empty YAML returns an empty dictionary.
    - YAML root must be a dictionary.
    - Environment variables use nested override syntax:
        AEGIS_EXCHANGE__PRIMARY=kraken
        AEGIS_MONITORING__METRICS_PORT=9091
        AEGIS_TRADING__DEFAULT_SYMBOL=ETH/USDT
    """
    import os
    from pathlib import Path

    try:
        import yaml
    except Exception as exc:
        raise RuntimeError("PyYAML is required for YAML config loading") from exc

    config_path = Path(path)

    if not config_path.exists():
        return {}

    with config_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)

    if loaded is None:
        config = {}
    elif isinstance(loaded, dict):
        config = loaded
    else:
        return {}

    def coerce_env_value(raw_value: str):
        try:
            parsed = yaml.safe_load(raw_value)
            return parsed
        except Exception:
            return raw_value

    def set_nested_value(target: dict, nested_keys: list[str], value):
        current = target

        for key in nested_keys[:-1]:
            normalized_key = key.lower()

            existing = current.get(normalized_key)

            if not isinstance(existing, dict):
                current[normalized_key] = {}

            current = current[normalized_key]

        final_key = nested_keys[-1].lower()
        current[final_key] = value

    prefix = "AEGIS_"

    for env_name, env_value in os.environ.items():
        if not env_name.startswith(prefix):
            continue

        nested_key_raw = env_name[len(prefix):]

        if "__" not in nested_key_raw:
            continue

        nested_keys = [
            part.strip()
            for part in nested_key_raw.split("__")
            if part.strip()
        ]

        if not nested_keys:
            continue

        coerced_value = coerce_env_value(env_value)

        set_nested_value(
            config,
            nested_keys,
            coerced_value,
        )

    return config

def _load_yaml(path: Path) -> dict:
    if not path.exists():
        log.warning("configs: %s not found Ã¢â‚¬â€ using empty config", path)
        return {}

    try:
        import yaml  # PyYAML
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
            log.debug("configs: loaded %s", path)
            return data or {}
    except ImportError:
        log.warning(
            "PyYAML not installed Ã¢â‚¬â€ falling back to raw text parse. "
            "Run: pip install pyyaml"
        )
        return _parse_yaml_naive(path)
    except Exception:
        log.exception("configs: failed to load %s", path)
        return {}


def _apply_env_overrides(config: dict, prefix: str) -> None:
    """
    Walk environment variables and patch matching keys into *config*.
    Numeric strings are auto-cast to int/float.
    """
    for key, raw_value in os.environ.items():
        if not key.startswith(prefix):
            continue
        # Strip prefix, split on __ to get nested path
        path_parts = key[len(prefix):].lower().split("__")
        value      = _cast(raw_value)
        _set_nested(config, path_parts, value)
        log.debug("configs: env override %s = %r", key, value)


def _set_nested(d: dict, keys: list[str], value) -> None:
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


def _cast(s: str):
    """Try int Ã¢â€ â€™ float Ã¢â€ â€™ bool Ã¢â€ â€™ keep as str."""
    for fn in (int, float):
        try:
            return fn(s)
        except ValueError:
            pass
    if s.lower() in {"true",  "yes", "1"}: return True
    if s.lower() in {"false", "no",  "0"}: return False
    return s


def _parse_yaml_naive(path: Path) -> dict:
    """
    Minimal key: value parser used when PyYAML is not available.
    Handles only flat scalar values and one level of nesting via indentation.
    Good enough to read the defaults config without a hard dependency.
    """
    result: dict  = {}
    current: dict = result
    current_key   = None

    with open(path, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.rstrip()
            if not stripped or stripped.startswith("#"):
                continue
            indent  = len(line) - len(line.lstrip())
            content = stripped.lstrip()
            if ":" not in content:
                continue
            k, _, v = content.partition(":")
            k = k.strip()
            v = v.strip()
            if indent == 0:
                current_key = k
                if v:
                    result[k] = _cast(v)
                    current   = result
                else:
                    result[k] = {}
                    current   = result[k]
            else:
                if v:
                    current[k] = _cast(v)

    return result