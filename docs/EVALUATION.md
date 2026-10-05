# Evaluation index / 평가 목록

Every number below is copied from the linked report or raw result file. The sets are small and synthetic: they are regression checks written by the author, not external benchmarks, and several were written after seeing earlier failures. Failures are kept in place rather than re-run until they pass.

아래 숫자는 모두 연결된 보고서나 원시 결과에서 그대로 옮겼습니다. 평가 집합은 작고 합성된 자료이며, 외부 벤치마크가 아니라 작성자가 만든 회귀 확인입니다. 일부는 앞선 실패를 본 뒤 작성했습니다. 실패한 결과는 통과할 때까지 재실행하지 않고 그대로 남겼습니다.

**Reading rules / 읽는 법**
- `completed` (or "structure passed") means the run finished with a well-formed, evidence-linked output. It is **not** a correctness score; correctness is scored separately.
- "Held-out" sets here were written after the author saw earlier error types. None of them is a blind test.
- Model: `qwen3:4b-instruct-2507-q4_K_M` unless noted, Ollama 0.34.4, `temperature=0`, `num_ctx=4096`, `num_predict=768`, `think=false`, Apple M5 Pro.

## Part 1 — Evidence-grounded job posting analysis

| Evaluation | What it measures | n | Result | Caveat | Evidence |
|---|---|---:|---|---|---|
| Keyword search baseline | Recall@5 of the expected paragraph | 8 queries | 6/6 queries with expected evidence found; 2 no-evidence queries returned nothing | A negated sentence ("did not use R") is still retrieved, so retrieval is not proof of a qualification | [eval/README](../eval/README.md) |
| JD extraction, 2 models | Structure and quote check, then field accuracy | 4 postings | 4B: structure 4/4, each field 3/4. 1.7B: structure 3/4 (invented a year that is not in the text) | Passing the quote check did not prevent wrong company/role picks | [phase3_results.json](../eval/phase3_results.json) |
| JD extraction, 20 postings | Same, larger set | 20 | `jd-extract-v3`: structure 20/20, role 20/20, company 19/20. Current `jd-extract-v5` with omission checks: 18/20 across fields | v5 trades two rejections for stricter duty/marker checks | [v3](../eval/phase4_jd_20_v3_results.json), [current](../eval/phase4_jd_20_current_results.json) |
| Requirement matching, contract iterations | Structure/ID validity vs expected verdict | 12 → 20 | v3: 7/12 structure, 5/12 verdict. v4: 12/12, 9/12. **v5: 20/20, 18/20** | Expected verdicts and reasons were written before running | [v3](../eval/phase4_match_v3_results.json), [v4](../eval/phase4_match_v4_results.json), [v5](../eval/phase4_match_v5_results.json) |
| Same contract, smaller model | Model size effect under an identical contract | 20 | 1.7B: structure 20/20, **verdict 5/20**, including 3 wrong `supported` verdicts | Shows why structure checks alone are not quality | [v5 1.7B](../eval/phase4_match_v5_1p7b_results.json) |
| Additional 8 matching cases | Generalization beyond the 20 | 8 | `match-v5` 5/8; with an extra instruction 7/8 (but 17/20 on the original 20) | Written after seeing the error types; not blind | [v5](../eval/phase4_match_holdout_v5_results.json), [v7 trial](../eval/phase4_match_holdout_v7_trial_results.json) |
| Full workflow, 20 cases | JD extraction → retrieval → per-requirement verdict, each in a fresh DB | 20 | JD 20/20, Recall@5 21/21, **verdict 16/20**; application status untouched 20/20 | The 18/20 vs 16/20 gap was traced case by case in an input audit | [workflow](../eval/phase4_workflow_20_results.json), [repeat](../eval/phase4_workflow_20_repeat_results.json) |
| Image posting input (OCR) | macOS Vision OCR plus human comparison before saving | synthetic images | Misreadings recorded by type; nothing is saved without an explicit "compared with the original" check | Qualitative; no accuracy number is claimed | [ocr_ui](../eval/ocr_ui_2026-10-01.md) |

## Part 2 — Bounded read-only workspace agent

| Evaluation | What it measures | n | Result | Caveat | Evidence |
|---|---|---:|---|---|---|
| Custom JSON tool protocol | Can a 4B model drive tools through a hand-written JSON contract? | 20 | JSON shape 20/20, but correct tool + policy pass + successful execution **4/14** | Shape is not usability | [phase 0.5](../eval/agent_phase05_report_2026-10-01.md) |
| Custom JSON vs native tool calling | Same 6 requests through Ollama native `tool_calls` | 6 | Argument contract 4/6 → 6/6; policy pass 4/6 → 6/6 | Prompt and other conditions also differed; not a clean causal comparison | [native basic6](../eval/agent_phase05_native_basic6_report_2026-10-02.md) |
| Generalization to new requests | Baseline vs candidate prompt | 8 | Both 8/8 on tool choice and grounded answers; candidate costs more prompt tokens (13,629 → 17,131) | Small set | [0.6-B](../eval/agent_phase06b_generalization_2026-10-05.md) |
| CLI demo, fixed 6 cases | End-to-end `agent-read` | 6 | Phase 1: 5/6 (two tool calls in one turn were unsupported). Phase 1.1: 6/6. Re-scored offline with stricter scorer v3: unchanged | Regression set, seen during development | [rerun](../eval/agent_phase1_cli_demo_report_rerun_2026-10-05.md), [1.1](../eval/agent_phase1_1_report_2026-10-06.md), [v3 rescore](../eval/agent_phase1_cli_rescore_scorer_v3_2026-10-06.json) |
| Representative check after hardening | Read, search, batch, no-match, excluded file | 5 | 4 completed, 1 intended policy rejection with zero tool executions | Small | [Phase 1.2 model check](../eval/agent_phase12_model_report_2026-10-06.md) |
| Synthetic coding project usability | 12 requests incl. blocked file, outside symlink, injected instruction | 12 | **10/12 strict.** Policy rejected `.ENV` and the outside symlink before any file opened; 0 marker leaks. Failures: used search instead of read for a value (answer still right); obeyed an instruction hidden in a file | One-shot run, no prompt tuning afterwards | [usability report](../eval/agent_phase12_usability_report_2026-10-06.md) |
| Context overflow behavior | What Ollama does when history exceeds `num_ctx` | 11 requests | Default request silently dropped older messages (4772 → 3542 prompt tokens) and answered `UNKNOWN` with `done_reason=stop`. With `truncate=false` the server rejects; the agent now ends as `context_budget_exceeded` | `shift=false` effect not verified | [follow-up report](../eval/agent_phase12_followup_report_2026-10-06.md), [raw](../eval/agent_phase12_context_check_2026-10-06.json) |
| Pre-registered indirect prompt injection | Planted instructions in files: canary, forbidden tool call, unrequested read, false answer, refusal; plus controls | 14 dev + 24 sealed test | Test attack success by the registered measure: 1/18 baseline → 0/18 with mitigation v4; 0/36 hijack attempts; controls 5/6 → 4/6; attack-case task success 12/18 → 13/18. Registered rule met, but on one case (McNemar p = 1.0); v4 not adopted | The registered canary detector missed spaced echoes (exploratory: 2/6 → 1/6); the one control regression is plausibly caused by v4 | [report](../eval/agent_injection_2026-10-06/REPORT.md), [pre-registration](../eval/agent_injection_2026-10-06/PREREGISTRATION.md) |
| Replay demo | Do recorded runs reproduce exactly on current code? | 6 | 6/6 reproduce status and final answer, including the known failure | Replays model output; it does not re-test the model | [demo/replays](../demo/replays) |

## Independent review

Cross-model audits found defects that the author's own tests had missed: a scorer that passed wrong answers, case-variant bypasses of the secret-file policy, a log write that could disagree with the returned status, and absolute host paths leaking into the model context. Each audit claim was reproduced before it was fixed, and claims that did not reproduce were recorded as such.

다른 모델로 수행한 교차 감사가 작성자의 테스트로는 놓친 결함을 찾았습니다. 틀린 답을 통과시키는 채점기, 대소문자 변형으로 비밀 파일 정책을 우회하는 문제, 반환 상태와 다를 수 있는 로그 저장, 모델 문맥으로 새는 절대 경로가 그 예입니다. 감사 지적은 모두 재현한 뒤에 고쳤고, 재현되지 않은 지적도 그 사실을 기록했습니다.

- [Full audit](../eval/review_claude_full_audit_2026-10-06.md) · [Phase 1.2 report](../eval/agent_phase1_2_report_2026-10-06.md) · [Follow-up report](../eval/agent_phase12_followup_report_2026-10-06.md)
