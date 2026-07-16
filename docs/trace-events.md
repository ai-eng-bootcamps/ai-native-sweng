# Trace event standard

All major harness components emit structured trace events (continuous project specification,
section 19). This document defines the on-disk format implemented in
`src/anse_harness/tracing/`.

## File format

A trace is a JSONL file: one JSON object per line, one line per event, in emission order.
One file holds one run. Traces are written under `traces/` (gitignored); committed examples
live in `traces/examples/`.

## Event fields

| Field             | Type           | Meaning                                                        |
|-------------------|----------------|----------------------------------------------------------------|
| `timestamp`       | string         | ISO 8601 timestamp with UTC offset                             |
| `event_id`        | string         | Unique id for this event (referenced by children)              |
| `run_id`          | string         | Id of the run that produced the event                          |
| `workflow_id`     | string         | Id of the workflow definition in effect                        |
| `component`       | string         | Emitting component, e.g. `models`, `workflows`, `tools`        |
| `event_type`      | string         | One of the event categories below                              |
| `status`          | string         | Outcome of the step, e.g. `ok` or `error`                      |
| `parent_event_id` | string or null | The event this one answers or belongs to, where relevant       |
| `payload`         | object         | Structured, event-type-specific data                           |
| `sensitivity`     | string         | Sensitive-data classification: `public` or `sensitive`         |
| `sensitive_keys`  | array          | Payload keys (at any depth) redacted by the writer             |

## Event categories

`run_started`, `run_completed`, `run_failed`, `model_requested`, `model_responded`,
`model_failed`, `context_packet_created`, `tool_requested`, `policy_evaluated`,
`approval_requested`, `approval_resolved`, `tool_completed`, `tool_failed`,
`state_transitioned`, `worker_started`, `worker_completed`, `worker_failed`,
`validation_started`, `validation_completed`, `checkpoint_created`, `retry_scheduled`,
`escalation_created`, `budget_updated`, `budget_exhausted`, `artifact_created`.

Unknown event types are rejected at construction time.

## Sensitive data

Sensitive content is never logged indiscriminately. An event carries a `sensitivity`
classification, and any payload key listed in `sensitive_keys` has its value replaced with
`[REDACTED]` by the trace writer - at any nesting depth - before the event reaches disk.

## Model interactions and replay

Model calls are recorded as a pair of events:

- `model_requested` with `payload.request` = `{messages, tools, response_schema, max_tokens}`
- `model_responded` with `payload.response` =
  `{text, tool_calls, structured_output, usage, stop_reason}` and `parent_event_id` pointing
  at the matching `model_requested` event

The replay model mode (`ReplayAdapter`) consumes exactly this format: it pairs each
`model_responded` event with its parent request, verifies incoming request messages against
the recorded ones, and re-serves the recorded responses in order. See
`traces/examples/investigation-demo.jsonl` for a complete recorded run.
