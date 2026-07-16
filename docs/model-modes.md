# Model execution modes

All model providers are accessed through the provider-neutral adapter in
`src/anse_harness/models/`. The platform supports three execution modes (spec 5.3); core
labs default to **scripted** or **replay**, so no API key or provider SDK is required to
work through most of the course.

## Configuration

Model configuration lives in TOML files under `configs/models/` and is loaded with
`anse_harness.models.load_model_config` / `create_adapter_from_file`. Relative paths are
resolved against the config file's directory.

```toml
mode = "scripted"            # "live" | "scripted" | "replay"

[scripted]
script = "scripted-demo.json"          # JSON list of predefined responses

[replay]
trace = "../../traces/examples/investigation-demo.jsonl"   # JSONL trace file

[live]
provider = "anthropic"       # "anthropic" (default) | "openai" | "gemini"
model = "claude-opus-4-8"

[live.cost]
input_usd_per_mtok = 5.0     # cost table used by the adapter's cost hook
output_usd_per_mtok = 25.0
```

## Scripted mode

Returns predefined responses from an in-memory script or a JSON script file, in order.
Deterministic; fails loudly on script exhaustion or when a request does not match the
expectation recorded for the next step. Used for unit and integration tests of execution
loops, tool calls, state transitions, approval logic, retries, and termination.

## Replay mode

Replays previously captured model interactions from a JSONL trace file (format:
`docs/trace-events.md`). Used for demonstrations, debugging, low-cost labs, and regression
testing. Incoming requests must match the recorded requests.

## Live mode

Calls a real provider API. The default live provider is **Anthropic**; **OpenAI** and
**Gemini** are fallbacks. Providers are accessed via their APIs only - never via
coding-agent CLIs. The provider SDKs are an optional dependency:

```sh
uv sync --extra live
```

Without the extra installed, selecting live mode raises a clear `MissingProviderSDKError`;
scripted and replay modes work with zero provider SDKs installed. Credentials come from the
standard provider environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`GEMINI_API_KEY`).
