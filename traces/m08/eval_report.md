# Module 8 fixture evaluation: guided vs terse prompt (baseline D)

Mode: scripted. Every figure in this report was produced in this mode and is labeled with its measurement category (canonical section 7).

Repeated runs in this mode are identical by construction: model responses are fixed, so re-running reproduces the same result at zero live model spend. The absence of spread below is a property of the mode, not evidence of reliability; success-rate variance, flaky rates, and pass@k are properties of live runs only.

## Results by task and configuration

| task | configuration | mode | runs | repetitions | pass rate (outcome) | attributed model cost USD (economic) | mean duration s (process) | tool calls (process) | failure classes (process) | infrastructure runs (excluded from denominator) |
|---|---|---|---|---|---|---|---|---|---|---|
| fx-slug-hyphen | cfg-guided | scripted | 1 | 1 (identical by construction) | 100% | 0.007620 | 0.223 | 3 | - | 0 |
| fx-slug-hyphen | cfg-terse | scripted | 1 | 1 (identical by construction) | 100% | 0.002712 | 0.213 | 1 | - | 0 |
| fx-slug-tests | cfg-guided | scripted | 1 | 1 (identical by construction) | 100% | 0.007455 | 0.207 | 2 | - | 0 |
| fx-slug-tests | cfg-terse | scripted | 1 | 1 (identical by construction) | 0% | 0.003420 | 0.215 | 1 | implementation failure x1 | 0 |

Pass-rate denominators count graded runs only; infrastructure failures (harness, environment, or grader faults) are shown in their own column and never counted as task failures.

## Grader versions

- fx-slug-hyphen @ 1c09f3cef7f9
- fx-slug-tests @ 77e79ed42bbf

## Claim checklist (canonical 7.7)

- Task set: fx-slug-hyphen, fx-slug-tests over the m05 practice fixture repository (pinned baseline revision)
- Baseline: configuration D (bounded write agent, Module 3 loop) for every cell
- Configuration: cfg-guided vs cfg-terse (prompt A/B over the same unchanged runtime); cost table 3/15 USD per Mtok
- Grader: fixture hidden graders fx-slug-hyphen and fx-slug-tests (content-hash versions listed above)
- Number of runs: 1 per task and configuration, scripted mode
- Limitations: scripted mode: model responses are fixed, so run-to-run variance is zero by construction and live model spend is $0; these runs demonstrate the evaluation pipeline, not live-model reliability. Live distributions require funded live runs (pending an owner decision on live evaluation runs).
