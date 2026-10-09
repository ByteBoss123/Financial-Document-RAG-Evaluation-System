"""Held-out check of the numeric-hallucination detector on TAT-QA (NExTplusplus/TAT-QA), real annual-report
tables and text with expert answers. Not looked at while the value-matching fix was built.

Uses extracted answers only (answer_type span / multi-span) that contain a non-year figure; context is the
report's table cells plus paragraphs. Clean = gold answer (with its scale word), wrong = every figure +10%."""
import importlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
fd = importlib.import_module("app.failure_detection")
YEAR = re.compile(r"(19|20)\d{2}")


def perturb(ans, k=1.10):
    def f(m):
        s = m.group(0)
        d = s.replace(",", "")
        if YEAR.fullmatch(d):
            return s
        try:
            v = float(d)
        except ValueError:
            return s
        return f"{v * k:.2f}" if "." in d else f"{int(round(v * k))}"
    return re.sub(r"\d[\d,]*\.?\d*", f, ans)


def reformat(ans, scale):
    """How an LLM typically restates a table figure: no thousands separators, 2 decimals, and the next unit
    up when the value is 1,000 or more ("$1,496.5 million" -> "$1.50 billion")."""
    up = {"thousand": "million", "million": "billion"}

    def f(m):
        s = m.group(0)
        d = s.replace(",", "")
        if YEAR.fullmatch(d):
            return s
        v = float(d)
        if scale in up and v >= 1000:
            return f"{v / 1000:.2f} {up[scale]}"
        return f"{v:.2f}"
    out = re.sub(r"\d[\d,]*\.?\d*", f, ans)
    if scale in up and up[scale] in out:
        out = out.replace(f" {scale}", "")
    return out


def items(path, rewrite=False):
    for doc in json.load(open(path)):
        ctx = "\n".join(" | ".join(row) for row in doc["table"]["table"]) + "\n" + \
              "\n".join(p["text"] for p in doc["paragraphs"])
        for q in doc["questions"]:
            if q["answer_type"] not in ("span", "multi-span"):
                continue
            ans = q["answer"] if isinstance(q["answer"], list) else [q["answer"]]
            unit = f" {q['scale']}" if q["scale"] and q["scale"] != "percent" else ""
            if rewrite:
                text = ", ".join(reformat(f"{a}{unit}", q["scale"]) for a in ans)
            else:
                text = ", ".join(map(str, ans)) + unit
            if perturb(text) == text:  # no figure to check
                continue
            yield q["uid"], text, ctx


def run(rows):
    flag = fd.check_numeric_hallucination
    fp = [u for u, a, c in rows if flag(a, c)]
    caught = sum(1 for u, a, c in rows if flag(perturb(a), c))
    n = len(rows)
    return {"n": n, "false_alarms_on_gold": len(fp), "false_alarm_rate": round(len(fp) / n, 4),
            "wrong_plus10pct_caught": caught, "recall_plus10pct": round(caught / n, 4), "fp_examples": fp[:10]}


if __name__ == "__main__":
    tag = sys.argv[1] if len(sys.argv) > 1 else "run"
    base = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data" / "tatqa"
    out = {"source": "NExTplusplus/TAT-QA dataset_raw dev + test_gold",
           "dev": run(list(items(base / "tatqa_dataset_dev.json"))),
           "test_gold": run(list(items(base / "tatqa_dataset_test_gold.json"))),
           "dev_reformatted": run(list(items(base / "tatqa_dataset_dev.json", True))),
           "test_gold_reformatted": run(list(items(base / "tatqa_dataset_test_gold.json", True)))}
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / f"results/heldout_tatqa_{tag}.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: {x: y for x, y in v.items() if x != "fp_examples"} if isinstance(v, dict) else v
                      for k, v in out.items()}, indent=1))
