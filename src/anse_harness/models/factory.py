"""Model configuration loading and adapter selection (spec 5.3, 20, 21).

Configuration lives in TOML files under configs/models/ (documented in
docs/model-modes.md). The mode key selects live, scripted, or replay; the
matching section supplies mode-specific settings. Relative script and trace
paths are resolved against the directory containing the config file.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from anse_harness.models.adapter import ModelAdapter
from anse_harness.models.errors import ConfigError
from anse_harness.models.replay import ReplayAdapter
from anse_harness.models.scripted import ScriptedAdapter
from anse_harness.models.types import CostTable

MODES = ("live", "scripted", "replay")
PROVIDERS = ("anthropic", "openai", "gemini")


@dataclass(frozen=True)
class ModelConfig:
    """Parsed model configuration (spec 20: model provider, model, cost table)."""

    mode: str
    provider: str = "anthropic"
    model: str = ""
    script_path: Path | None = None
    trace_path: Path | None = None
    cost_table: CostTable = field(default_factory=CostTable)


def load_model_config(path: Path) -> ModelConfig:
    """Load a ModelConfig from a TOML file (see configs/models/default.toml)."""
    try:
        with path.open("rb") as f:
            data: dict[str, Any] = tomllib.load(f)
    except FileNotFoundError as exc:
        raise ConfigError(f"model config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in model config {path}: {exc}") from exc

    mode = data.get("mode")
    if mode not in MODES:
        raise ConfigError(f"{path}: mode must be one of {MODES}, got {mode!r}")

    base = path.parent

    script_path: Path | None = None
    scripted = data.get("scripted", {})
    if "script" in scripted:
        script_path = base / str(scripted["script"])

    trace_path: Path | None = None
    replay = data.get("replay", {})
    if "trace" in replay:
        trace_path = base / str(replay["trace"])

    live = data.get("live", {})
    provider = str(live.get("provider", "anthropic"))
    model = str(live.get("model", ""))
    cost = live.get("cost", {})
    cost_table = CostTable(
        input_usd_per_mtok=float(cost.get("input_usd_per_mtok", 0.0)),
        output_usd_per_mtok=float(cost.get("output_usd_per_mtok", 0.0)),
    )

    return ModelConfig(
        mode=str(mode),
        provider=provider,
        model=model,
        script_path=script_path,
        trace_path=trace_path,
        cost_table=cost_table,
    )


def create_adapter(config: ModelConfig) -> ModelAdapter:
    """Create the adapter selected by the configuration's mode and provider."""
    if config.mode == "scripted":
        if config.script_path is None:
            raise ConfigError('scripted mode requires [scripted] script = "<path>"')
        return ScriptedAdapter.from_file(config.script_path, config.cost_table)

    if config.mode == "replay":
        if config.trace_path is None:
            raise ConfigError('replay mode requires [replay] trace = "<path>"')
        return ReplayAdapter(config.trace_path, config.cost_table)

    if config.mode == "live":
        if not config.model:
            raise ConfigError('live mode requires [live] model = "<model id>"')
        if config.provider == "anthropic":
            from anse_harness.models.live_anthropic import AnthropicAdapter

            return AnthropicAdapter(config.model, config.cost_table)
        if config.provider == "openai":
            from anse_harness.models.live_openai import OpenAIAdapter

            return OpenAIAdapter(config.model, config.cost_table)
        if config.provider == "gemini":
            from anse_harness.models.live_gemini import GeminiAdapter

            return GeminiAdapter(config.model, config.cost_table)
        raise ConfigError(f"unknown provider {config.provider!r}; expected one of {PROVIDERS}")

    raise ConfigError(f"unknown mode {config.mode!r}; expected one of {MODES}")


def create_adapter_from_file(path: Path) -> ModelAdapter:
    """Convenience: load a config file and create the adapter it selects."""
    return create_adapter(load_model_config(path))
