"""Unit tests for model configuration loading and mode/provider selection (spec 5.3, 20)."""

import importlib.util
from pathlib import Path

import pytest

from anse_harness.models import (
    ConfigError,
    MissingProviderSDKError,
    ModelConfig,
    ReplayAdapter,
    ScriptedAdapter,
    create_adapter,
    load_model_config,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "models" / "default.toml"


def test_load_default_config_selects_scripted_mode() -> None:
    config = load_model_config(DEFAULT_CONFIG)
    assert config.mode == "scripted"
    assert config.provider == "anthropic"
    assert config.model == "claude-opus-4-8"
    assert config.cost_table.input_usd_per_mtok == 5.0
    adapter = create_adapter(config)
    assert isinstance(adapter, ScriptedAdapter)


def test_replay_mode_selects_replay_adapter(tmp_path: Path) -> None:
    config_file = tmp_path / "model.toml"
    trace = REPO_ROOT / "traces" / "examples" / "investigation-demo.jsonl"
    config_file.write_text(f'mode = "replay"\n\n[replay]\ntrace = "{trace}"\n')
    adapter = create_adapter(load_model_config(config_file))
    assert isinstance(adapter, ReplayAdapter)


def test_relative_paths_resolve_against_config_directory() -> None:
    config = load_model_config(DEFAULT_CONFIG)
    assert config.script_path is not None
    assert config.script_path.parent == DEFAULT_CONFIG.parent
    assert config.script_path.exists()


def test_unknown_mode_rejected(tmp_path: Path) -> None:
    config_file = tmp_path / "model.toml"
    config_file.write_text('mode = "psychic"\n')
    with pytest.raises(ConfigError, match="mode"):
        load_model_config(config_file)


def test_missing_config_file_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_model_config(tmp_path / "nope.toml")


def test_unknown_provider_rejected() -> None:
    config = ModelConfig(mode="live", provider="acme", model="acme-1")
    with pytest.raises(ConfigError, match="unknown provider"):
        create_adapter(config)


def test_live_mode_requires_model() -> None:
    with pytest.raises(ConfigError, match="model"):
        create_adapter(ModelConfig(mode="live", model=""))


@pytest.mark.skipif(
    importlib.util.find_spec("anthropic") is not None,
    reason="anthropic SDK installed; the missing-SDK error path does not apply",
)
def test_live_mode_without_sdk_gives_clean_error() -> None:
    with pytest.raises(MissingProviderSDKError, match="uv sync --extra live"):
        create_adapter(ModelConfig(mode="live", provider="anthropic", model="claude-opus-4-8"))
