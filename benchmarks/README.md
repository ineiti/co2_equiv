# Model benchmarks

Saved runs of `scripts/benchmark_models.py` so model choice can be compared
without re-running inference. Each file is a full result set (30 test
prompts x 3 repeats, with raw model output and llama-server timings per
attempt) from one model.

## Results

- `results/gemma-4-E4B-it-Q4_0.json` — `unsloth/gemma-4-E4B-it-GGUF`, Q4_0
  (current default in `.env.example`).
- `results/apertus-8b-instruct-2509-Q4_0.json` — `unsloth/Apertus-8B-Instruct-2509-GGUF`,
  Q4_0.

Both runs used `llama-server --threads 4 --parallel 1 -ngl 99` (Metal GPU
offload) on the same machine, not the CPU-only config in
`docker-compose.yaml` — so absolute latency in these files does not
transfer directly to production, only the relative comparison and the
accuracy/reliability numbers do.

## Reproducing or comparing

```sh
# Re-print the summary table from saved runs (no inference needed):
devbox run -- bash -c '. $VENV_DIR/bin/activate && python3 scripts/benchmark_models.py \
  --summarize benchmarks/results/gemma-4-E4B-it-Q4_0.json benchmarks/results/apertus-8b-instruct-2509-Q4_0.json'

# Re-run against a live llama-server and save a new result file:
devbox run -- bash -c '. $VENV_DIR/bin/activate && python3 scripts/benchmark_models.py \
  --url http://localhost:8080/v1/chat/completions --label <name> --out benchmarks/results/<name>.json'
```

## Summary (2026-10-08)

| Metric                              | Gemma 4 E4B | Apertus-8B-Instruct-2509 |
| ----------------------------------- | ----------- | ------------------------ |
| Correct                             | 68/90 (76%) | 52/90 (58%)              |
| Wrong value                         | 10/90 (11%) | 25/90 (28%)              |
| Correctly flagged "unknown"         | 12/90 (13%) | 7/90 (8%)                |
| Malformed/error output              | 0/90 (0%)   | 6/90 (7%)                |
| Valid JSON shape rate               | 100%        | 93%                      |
| Cases reliable (>=2/3 reps correct) | 27/30       | 20/30                    |
| Mean completion tokens              | 206         | 33                       |

Gemma's higher completion-token count is hidden chain-of-thought
(`reasoning_content`, stripped before JSON parsing), not slower per-token
generation — both models ran at a similar ~60-70 tok/s. Apertus skips that
reasoning step, so it answers faster per request but is also wrong more
often: observed failures include copying the wrong reference distance from
the system prompt's own EXAMPLES section (780 km Zurich-London reused for
a London-Paris query, which is 340 km) and replying in plain English
instead of the required `{"co2": "unknown"}` for off-topic input.

Apertus also has an optional "Deliberation" (thinking) mode, found by
inspecting its GGUF's embedded chat template (`enable_thinking`, same
mechanism as Qwen3; off by default). Unlike Gemma, it has no separate
hidden reasoning channel — enabling it makes the model write reasoning
inline inside whatever output field it's given, which breaks this app's
strict single-line JSON contract. It also isn't something
`backend/app/llm_client.py` sends, so it was not used in the benchmark
above.

**Recommendation:** keep Gemma 4 E4B as the default. Apertus runs cleanly
under llama.cpp but is less reliable at this app's exact task — structured
numeric estimation under a strict output contract — at a comparable model
size and quantization.
