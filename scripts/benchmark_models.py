#!/usr/bin/env python3
"""Benchmark a running llama-server (OpenAI-compatible /v1/chat/completions)
against a fixed test set, scoring JSON-shape validity, numeric accuracy
against hand-computed expected values from SYSTEM_PROMPT.md, and latency.

Usage:
  devbox run -- bash -c '. $VENV_DIR/bin/activate && python3 scripts/benchmark_models.py \\
      --url http://localhost:8080/v1/chat/completions --label gemma --out gemma.json'

  devbox run -- bash -c '. $VENV_DIR/bin/activate && python3 scripts/benchmark_models.py \\
      --url http://localhost:8080/v1/chat/completions --label apertus-cot \\
      --system-prompt benchmarks/SYSTEM_PROMPT_apertus_cot.md --out apertus-cot.json'

  devbox run -- bash -c '. $VENV_DIR/bin/activate && python3 scripts/benchmark_models.py \\
      --summarize gemma.json apertus.json'
"""

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.llm_client import _strip_think_block, _validate_shape  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SYSTEM_PROMPT_PATH = REPO_ROOT / "SYSTEM_PROMPT.md"

_CO2_PATTERN = re.compile(r"^-?\d+(\.\d+)?kg$")

# Each case: (input text, expected kg CO2e or None for "unknown", tolerance fraction)
# Expected values hand-computed from SYSTEM_PROMPT.md REFERENCE VALUES, independent
# of the EXAMPLES section so the model can't just copy an in-context example.
TEST_CASES = [
    # Transport, single leg, under 500 km flight factor
    ("Flight from London to Paris", 340 * 1.08 * 0.25, 0.3),
    # Return flight, long-haul, economy
    ("Return flight from Frankfurt to Singapore", 10300 * 2 * 1.08 * 0.15, 0.3),
    # Business class one-way
    ("Flight from Zurich to Dubai in business class", 4800 * 1.08 * 0.15 * 2.9, 0.3),
    # Train in Switzerland
    ("Took the train 120 km in Switzerland", 120 * 0.008, 0.4),
    # Electric car, France grid
    ("Drove an electric car 60 km in France", 60 * 0.02, 0.4),
    # "X instead of Y" -> negative
    ("Took the bus instead of driving 15 km", 15 * 0.10 - 15 * 0.17, 0.4),
    ("Biked 8 km instead of taking a taxi", 8 * 0 - 8 * 0.17, 0.4),
    # Carbon removal
    ("Planted a tree", -20, 0.3),
    ("Planted 3 trees two years ago", -20 * 3 * 2, 0.4),
    # Multiple items summed
    ("A cappuccino and a croissant for breakfast", 0.5 + 0.5, 0.5),
    ("Bought a smartphone and a pair of jeans", 70 + 25, 0.3),
    # Per period
    ("Showering for 10 minutes every day for a week", 0.5 * 7, 0.4),
    ("Commuting 10 km by car every day for a month (22 workdays)", 10 * 0.17 * 22, 0.4),
    # Food, per kg
    ("Ate 500g of beef", 35 * 0.5, 0.3),
    ("Bought 2 kg of chicken", 6 * 2, 0.3),
    # Non-European grid
    ("Charged an electric car with 50 kWh in India", 50 * 0.70, 0.4),
    ("Ran an air conditioner for 3 hours in the USA", 0.4 * 3, 0.4),
    # Household
    ("Ran the dishwasher twice", 0.3 * 2, 0.4),
    ("Took a bath", 1.2, 0.3),
    # Digital
    ("Streamed music for 5 hours", 0.005 * 5, 0.5),
    # Products / materials
    ("Bought 10 kg of steel", 2 * 10, 0.3),
    ("Bought a new electric car", 12000, 0.3),
    # Waste
    ("Threw away 2 kg of mixed waste in landfill", 0.5 * 2, 0.4),
    # Annual comparison framing (should still produce a number, not "unknown")
    ("My diet for a year, average", 4.5 * 365, 0.4),
    # Should be "unknown"
    ("Hello, how are you?", None, None),
    ("What is the capital of France?", None, None),
    ("asdkjalksdj qwoiuqwoiu", None, None),
    ("Tell me a joke", None, None),
    # Non-English (Apertus's claimed multilingual strength; Gemma may also handle these)
    ("Un vol aller-retour de Genève à Lisbonne", 1500 * 2 * 1.08 * 0.15, 0.3),
    ("Ich bin 30 km mit dem Zug in der Schweiz gefahren", 30 * 0.008, 0.4),
]

REPEATS = 3


def extract_json_object(content: str) -> dict:
    """Parse the model's JSON answer out of `content`. Handles three shapes:
    1. The whole (stripped) content is the JSON object (today's contract).
    2. A <think>...</think> block precedes it (handled by _strip_think_block).
    3. Free-text chain-of-thought precedes it with no tags (the CoT prompt
       variant) - take the last top-level {...} found at the end of the text.
    Raises json.JSONDecodeError/ValueError like json.loads would, so callers
    don't need a separate code path."""
    stripped = _strip_think_block(content).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    # Free-text CoT precedes the answer: find the last line starting with
    # '{' and parse from there, so prose mentioning e.g. "0.17" can't be
    # mistaken for the answer object.
    last_brace_line = None
    for line in stripped.splitlines():
        if line.lstrip().startswith("{"):
            last_brace_line = line.lstrip()
    if last_brace_line is None:
        raise json.JSONDecodeError("no JSON line found", stripped, 0)
    return json.loads(last_brace_line)


def call_once(client: httpx.Client, url: str, text: str, system_prompt: str) -> dict:
    """Returns a dict with raw response data plus the parsed/validated result
    (or an error) so failures can be inspected afterwards, not just counted."""
    record = {
        "raw_content": None,
        "result": None,
        "error": None,
        "prompt_ms": float("nan"),
        "predicted_ms": float("nan"),
        "predicted_n": None,
        "completion_tokens": None,
    }
    try:
        resp = client.post(
            url,
            json={
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                "max_tokens": 400,
            },
            timeout=180.0,
        )
        resp.raise_for_status()
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        timings = body.get("timings", {})
        usage = body.get("usage", {})
        record["prompt_ms"] = timings.get("prompt_ms", float("nan"))
        record["predicted_ms"] = timings.get("predicted_ms", float("nan"))
        record["predicted_n"] = timings.get("predicted_n")
        record["completion_tokens"] = usage.get("completion_tokens")
        record["raw_content"] = content
        if not isinstance(content, str):
            raise ValueError(f"expected string content, got: {content!r}")
        data = extract_json_object(content)
        record["result"] = _validate_shape(data)
    except Exception as exc:  # noqa: BLE001
        record["error"] = str(exc)
    return record


def extract_number(co2_str: str) -> float | None:
    m = _CO2_PATTERN.match(co2_str)
    if not m:
        return None
    return float(co2_str[:-2])


def score_case(result: dict | None, expected: float | None, tolerance: float | None) -> str:
    """Returns one of: shape_fail, correct, wrong_value, wrong_unknown, correct_unknown."""
    if result is None:
        return "shape_fail"
    co2 = result.get("co2")
    if expected is None:
        return "correct_unknown" if co2 == "unknown" else "wrong_unknown"
    if co2 == "unknown":
        return "wrong_value"
    num = extract_number(co2)
    if num is None:
        return "shape_fail"
    if expected == 0:
        ok = abs(num) < 0.5
    else:
        ok = abs(num - expected) <= abs(expected) * tolerance and (num >= 0) == (expected >= 0)
    return "correct" if ok else "wrong_value"


def warmup(client: httpx.Client, url: str, system_prompt: str) -> float:
    start = time.monotonic()
    call_once(client, url, "warmup", system_prompt)
    return time.monotonic() - start


def run(args):
    system_prompt_path = (
        Path(args.system_prompt).resolve() if args.system_prompt else DEFAULT_SYSTEM_PROMPT_PATH
    )
    system_prompt = system_prompt_path.read_text()

    results = []
    with httpx.Client() as client:
        print(f"[{args.label}] warming up...", file=sys.stderr)
        cold_s = warmup(client, args.url, system_prompt)
        print(f"[{args.label}] cold request took {cold_s:.1f}s", file=sys.stderr)

        for text, expected, tolerance in TEST_CASES:
            attempts = []
            for rep in range(REPEATS):
                record = call_once(client, args.url, text, system_prompt)
                outcome = (
                    score_case(record["result"], expected, tolerance)
                    if record["error"] is None
                    else "error"
                )
                attempts.append({"outcome": outcome, **record})
                shown = (
                    record["result"].get("co2")
                    if record["result"]
                    else record["error"]
                )
                print(
                    f"[{args.label}] {text[:40]!r:42} rep{rep} -> {outcome:16} {shown}",
                    file=sys.stderr,
                )
            results.append({"text": text, "expected": expected, "attempts": attempts})

    out_data = {
        "label": args.label,
        "system_prompt_path": str(system_prompt_path.relative_to(REPO_ROOT)),
        "cold_s": cold_s,
        "cases": results,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(out_data, indent=2))
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(json.dumps(out_data, indent=2))


def summarize(paths: list[str]):
    for path in paths:
        data = json.loads(Path(path).read_text())
        label = data["label"]
        outcomes = []
        completion_tokens = []
        for case in data["cases"]:
            for a in case["attempts"]:
                outcomes.append(a["outcome"])
                if a.get("completion_tokens") is not None:
                    completion_tokens.append(a["completion_tokens"])
        n = len(outcomes)
        c = Counter(outcomes)
        case_level_correct = sum(
            1
            for case in data["cases"]
            if sum(1 for a in case["attempts"] if a["outcome"] in ("correct", "correct_unknown")) >= 2
        )
        print(f"=== {label} ===")
        if data.get("system_prompt_path"):
            print(f"  system prompt: {data['system_prompt_path']}")
        print(f"  cold request: {data['cold_s']:.1f}s")
        print(f"  n={n} (cases={len(data['cases'])} x {REPEATS} reps)")
        for k in ["correct", "wrong_value", "correct_unknown", "wrong_unknown", "shape_fail", "error"]:
            print(f"  {k:16} {c.get(k, 0):3d}  ({100 * c.get(k, 0) / n:.0f}%)")
        valid_rate = 100 * (n - c.get("error", 0) - c.get("shape_fail", 0)) / n
        print(f"  valid-JSON-shape rate: {valid_rate:.0f}%")
        print(f"  cases with >=2/3 reps correct: {case_level_correct}/{len(data['cases'])}")
        if completion_tokens:
            print(f"  mean completion_tokens: {sum(completion_tokens) / len(completion_tokens):.0f}")
        print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="llama-server /v1/chat/completions URL")
    parser.add_argument("--label", help="label for this model in the report")
    parser.add_argument("--out", default=None, help="write JSON results to this path")
    parser.add_argument(
        "--system-prompt",
        default=None,
        help="path to a system prompt file to use instead of SYSTEM_PROMPT.md",
    )
    parser.add_argument(
        "--summarize",
        nargs="+",
        metavar="RESULTS_JSON",
        help="skip running; print a summary table for one or more result files written by --out",
    )
    args = parser.parse_args()

    if args.summarize:
        summarize(args.summarize)
        return

    if not args.url or not args.label:
        parser.error("--url and --label are required unless --summarize is used")
    run(args)


if __name__ == "__main__":
    main()
