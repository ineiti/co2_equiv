# Model benchmarks

Saved runs of `scripts/benchmark_models.py` so model choice can be compared
without re-running inference. Each file is a full result set (30 test
prompts x 3 repeats, with raw model output and llama-server timings per
attempt) from one model.

## Results

- `results/gemma-4-E4B-it-Q4_0.json` — `unsloth/gemma-4-E4B-it-GGUF`, Q4_0
  (current default in `.env.example`), with the production `SYSTEM_PROMPT.md`.
- `results/apertus-8b-instruct-2509-Q4_0.json` — `unsloth/Apertus-8B-Instruct-2509-GGUF`,
  Q4_0, with the production `SYSTEM_PROMPT.md`.
- `results/apertus-8b-instruct-2509-cot-Q4_0.json` — same Apertus model,
  with `SYSTEM_PROMPT_apertus_cot.md` (see below).

All runs used `llama-server --threads 4 --parallel 1 -ngl 99` (Metal GPU
offload) on the same machine, not the CPU-only config in
`docker-compose.yaml` — so absolute latency in these files does not
transfer directly to production, only the relative comparison and the
accuracy/reliability numbers do.

### The chain-of-thought prompt variant

`SYSTEM_PROMPT_apertus_cot.md` is a modified system prompt, used only for
this benchmark, that asks the model to write out its reasoning as three
explicit steps — ingredients (item + quantity/unit), matched reference
factor, then the arithmetic — in plain text, immediately followed by the
usual one-line JSON answer on its own final line. Apertus has no separate
hidden-reasoning channel the way Gemma/Qwen3 do (see "Deliberation" below),
so this is an attempt to get the same effect — forcing the model to work
through the problem step by step before committing to a number — via
prompting alone, with no backend changes. `scripts/benchmark_models.py`
supports this via `--system-prompt <path>`, and extracts the JSON from the
last line starting with `{` so free-text reasoning before it doesn't break
parsing.

## Reproducing or comparing

```sh
# Re-print the summary table from saved runs (no inference needed):
devbox run -- bash -c '. $VENV_DIR/bin/activate && python3 scripts/benchmark_models.py \
  --summarize benchmarks/results/gemma-4-E4B-it-Q4_0.json \
    benchmarks/results/apertus-8b-instruct-2509-Q4_0.json \
    benchmarks/results/apertus-8b-instruct-2509-cot-Q4_0.json'

# Re-run against a live llama-server and save a new result file:
devbox run -- bash -c '. $VENV_DIR/bin/activate && python3 scripts/benchmark_models.py \
  --url http://localhost:8080/v1/chat/completions --label <name> --out benchmarks/results/<name>.json'

# Re-run with a different system prompt (e.g. the CoT variant):
devbox run -- bash -c '. $VENV_DIR/bin/activate && python3 scripts/benchmark_models.py \
  --url http://localhost:8080/v1/chat/completions --label <name> \
  --system-prompt benchmarks/SYSTEM_PROMPT_apertus_cot.md --out benchmarks/results/<name>.json'
```

## Summary (2026-10-08)

| Metric                              | Gemma 4 E4B | Apertus (plain) | Apertus (CoT prompt) |
| ----------------------------------- | ----------- | --------------- | -------------------- |
| Correct                             | 68/90 (76%) | 52/90 (58%)     | 48/90 (53%)          |
| Wrong value                         | 10/90 (11%) | 25/90 (28%)     | 24/90 (27%)          |
| Correctly flagged "unknown"         | 12/90 (13%) | 7/90 (8%)       | 6/90 (7%)            |
| Malformed/error output              | 0/90 (0%)   | 6/90 (7%)       | 7/90 (8%)            |
| Shape fail (wrong JSON keys/format) | 0/90 (0%)   | 0/90 (0%)       | 5/90 (6%)            |
| Valid JSON shape rate               | 100%        | 93%             | 87%                  |
| Cases reliable (>=2/3 reps correct) | 27/30       | 20/30           | 19/30                |
| Mean completion tokens              | 206         | 33              | 108                  |

Gemma's higher completion-token count is hidden chain-of-thought
(`reasoning_content`, stripped before JSON parsing), not slower per-token
generation — both models ran at a similar ~60-70 tok/s. Apertus skips that
reasoning step, so it answers faster per request but is also wrong more
often: observed failures include copying the wrong reference distance from
the system prompt's own EXAMPLES section (780 km Zurich-London reused for
a London-Paris query, which is 340 km) and replying in plain English
instead of the required `{"co2": "unknown"}` for off-topic input.

**The explicit chain-of-thought prompt did not help, and slightly hurt.**
It does fix the specific example-copying failure in some cases — forced to
write "Ingredients: ... 340 km (London to Paris)" before anything else,
the model picked the correct reference distance more often than with the
plain prompt. But the extra free-form text gave it more surface area for
new mistakes: one response used markdown headers and then dropped the
required `"kg"` suffix (`"co2": "51"` instead of `"51kg"`), producing a
`shape_fail` that didn't exist in the plain-prompt run at all. The
refusal-for-off-topic-input problem was not fixed either — asked to "tell
me a joke," it refused in plain English twice and, worse, fully complied
and told an actual joke once, even though the CoT prompt's own step-by-step
instructions explicitly say to skip straight to `{"co2": "unknown"}` for
non-item input. Net effect across all 30 cases x 3 reps: slightly worse on
every metric than the plain prompt. Prompting alone is not enough to fix
either of Apertus's two main failure modes at this model size.

Apertus also has an optional "Deliberation" (thinking) mode, found by
inspecting its GGUF's embedded chat template (`enable_thinking`, same
mechanism as Qwen3; off by default). Unlike Gemma, it has no separate
hidden reasoning channel — enabling it makes the model write reasoning
inline inside whatever output field it's given, which breaks this app's
strict single-line JSON contract. It also isn't something
`backend/app/llm_client.py` sends, so it was not used in either Apertus
benchmark above; the CoT prompt variant achieves a similar "think before
answering" effect through prompting instead, with the caveats above.

**Recommendation:** keep Gemma 4 E4B as the default. Apertus runs cleanly
under llama.cpp but is less reliable at this app's exact task — structured
numeric estimation under a strict output contract — at a comparable model
size and quantization, and prompting changes alone don't close the gap.

## Open question: should the LLM do the arithmetic at all?

LLMs are known to be unreliable at exact multiplication/arithmetic, and
several of the `wrong_value` cases above are consistent with that — the
model identifies the right item and even the right factor, then makes an
arithmetic slip. The more robust fix is architectural, not prompt-level:
have the LLM only extract structured facts (matched category, quantity,
unit) and have deterministic Python code look up the factor and compute
the result, removing arithmetic from the LLM's job entirely. That's a
real backend change — a new output schema, a factor table in Python, and
a calculation step in `llm_client.py`/`main.py` — out of scope for this
prompt-only benchmark. Worth a follow-up if either model's residual
`wrong_value` rate is still too high for production use.
