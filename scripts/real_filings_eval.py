"""Evaluate FinDocQA's numeric-hallucination detector on real filing evidence.

Data: FinanceBench open-source sample (patronus-ai/financebench, 150 questions over real
10-K / 10-Q / earnings documents, each with expert gold answers and the supporting filing text).

Clean case   : gold answer + its filing evidence  -> should NOT be flagged (false alarm if flagged).
Wrong number : every non-year figure in the gold answer changed (x1.37+1, and a harder +10%)
               -> should be flagged.
Primary set  : FinanceBench "Information extraction" questions whose answer contains a figure
               (answers that are copied from the filing, not computed).
"""
import importlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
fd = importlib.import_module("app.failure_detection")
R = [json.loads(line) for line in open(ROOT / "data/financebench/financebench_open_source.jsonl")]


def ctx(r):
    return "\n".join(e["evidence_text"] for e in r["evidence"])


def perturb(ans, k=1.37, b=1.0):
    def f(m):
        s = m.group(0)
        d = s.replace(",", "")
        if re.fullmatch(r"(19|20)\d{2}", d):
            return s
        try:
            v = float(d)
        except ValueError:
            return s
        nv = v * k + b
        return f"{nv:.2f}" if "." in d else f"{int(round(nv))}"
    return re.sub(r"\d[\d,]*\.?\d*", f, ans)


def has_figure(s):
    return perturb(s) != s


EXT = [r for r in R if r["question_reasoning"] == "Information extraction" and has_figure(r["answer"])]
ALL = [r for r in R if has_figure(r["answer"])]


def run(rows, label):
    flag = fd.check_numeric_hallucination
    fp = [r["financebench_id"] for r in rows if flag(r["answer"], ctx(r))]
    c1 = sum(1 for r in rows if flag(perturb(r["answer"]), ctx(r)))
    c2 = sum(1 for r in rows if flag(perturb(r["answer"], 1.10, 0.0), ctx(r)))
    n = len(rows)
    return {"set": label, "n": n, "false_alarms_on_gold": len(fp), "false_alarm_rate": round(len(fp) / n, 4),
            "wrong_number_caught_x1.37": c1, "recall_x1.37": round(c1 / n, 4),
            "wrong_number_caught_plus10pct": c2, "recall_plus10pct": round(c2 / n, 4), "fp_ids": fp}


if __name__ == "__main__":
    tag = sys.argv[1] if len(sys.argv) > 1 else "run"
    res = {"source": "patronus-ai/financebench data/financebench_open_source.jsonl",
           "information_extraction": run(EXT, "information_extraction"),
           "all_answers_with_figures": run(ALL, "all_answers_with_figures (includes computed answers)")}
    res["all_answers_with_figures"].pop("fp_ids")
    json.dump(res, open(ROOT / f"results/real_filings_numeric_{tag}.json", "w"), indent=1)
    print(json.dumps(res, indent=1))
