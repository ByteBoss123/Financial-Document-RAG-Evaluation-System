"""One-command redeploy for the FinDocQA Lambda: build -> deploy -> smoke test -> automatic rollback.

    python infra/redeploy.py                 # build from s3://<bucket>/src/, deploy, smoke test
    python infra/redeploy.py --rollback-drill  # also prove rollback: roll back, smoke test, roll forward

Build: CodeBuild project `findocqa-build` (cloud Docker build, pushes to the ECR repo; no local Docker).
Deploy: UpdateFunctionCode to the new image digest, wait until LastUpdateStatus is Successful.
Smoke test: one question per filer; every call must return HTTP 200, a non-error answer, and a top source from
the company the question names. Any failure rolls the function back to the previous image digest and re-tests.
Requires AWS credentials with codebuild:StartBuild/BatchGetBuilds, logs:GetLogEvents,
lambda:GetFunction/UpdateFunctionCode/GetFunctionConfiguration/InvokeFunction.
"""
import argparse
import json
import re
import sys
import time

import boto3

REGION = "us-east-1"
FUNCTION = "findocqa-FinDocQAFunction-cV7MZUoWpdyH"
PROJECT = "findocqa-build"
REPO_URI = "331604528033.dkr.ecr.us-east-1.amazonaws.com/findocqac4d0723d/findocqafunction00622456repo"
SMOKE = [
    ("How many employees does Morgan Stanley have?", "MORGAN STANLEY"),
    ("What were JPMorgan Chase's total net revenues for 2025?", "JPMORGAN"),
    ("What regulatory risks does Goldman Sachs identify?", "GOLDMAN"),
    ("What does BGC say about its Fenics business?", "BGC"),
    ("How does ICE describe its mortgage technology business?", "Intercontinental"),
]


def build(cb, logs):
    bid = cb.start_build(projectName=PROJECT)["build"]["id"]
    while True:
        b = cb.batch_get_builds(ids=[bid])["builds"][0]
        if b["buildStatus"] != "IN_PROGRESS":
            break
        time.sleep(20)
    if b["buildStatus"] != "SUCCEEDED":
        raise RuntimeError(f"build {bid} {b['buildStatus']}")
    ev = logs.get_log_events(logGroupName=b["logs"]["groupName"], logStreamName=b["logs"]["streamName"],
                             startFromHead=False, limit=200)["events"]
    digest = next(m.group(1) for e in reversed(ev) if (m := re.search(r"digest: (sha256:[0-9a-f]+)", e["message"])))
    return f"{REPO_URI}@{digest}"


def deploy(lam, image_uri):
    lam.update_function_code(FunctionName=FUNCTION, ImageUri=image_uri)
    while lam.get_function_configuration(FunctionName=FUNCTION).get("LastUpdateStatus") == "InProgress":
        time.sleep(5)
    status = lam.get_function_configuration(FunctionName=FUNCTION)["LastUpdateStatus"]
    if status != "Successful":
        raise RuntimeError(f"deploy {status}")


def ask(lam, question):
    ev = {"httpMethod": "POST", "path": "/ask", "resource": "/{proxy+}", "pathParameters": {"proxy": "ask"},
          "headers": {"Content-Type": "application/json"}, "isBase64Encoded": False,
          "requestContext": {"httpMethod": "POST", "path": "/ask", "resourcePath": "/{proxy+}", "stage": "Prod"},
          "body": json.dumps({"question": question}), "queryStringParameters": None}
    t = time.perf_counter()
    out = json.loads(lam.invoke(FunctionName=FUNCTION, Payload=json.dumps(ev))["Payload"].read())
    return out.get("statusCode"), json.loads(out.get("body") or "{}"), (time.perf_counter() - t) * 1000


def smoke_test(lam):
    results = []
    for q, company in SMOKE:
        code, body, ms = ask(lam, q)
        src = (body.get("sources") or [{}])[0].get("company", "")
        answered = not body.get("answer", "").startswith("[generation error")
        ok = code == 200 and answered and company.lower() in src.lower()
        results.append({"question": q, "status": code, "top_source": src, "ok": ok, "ms": round(ms)})
    return all(r["ok"] for r in results), results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rollback-drill", action="store_true")
    args = ap.parse_args()
    s = boto3.Session(region_name=REGION)
    cb, logs, lam = s.client("codebuild"), s.client("logs"), s.client("lambda")
    previous = lam.get_function(FunctionName=FUNCTION)["Code"]["ImageUri"]
    t0 = time.time()
    new = build(cb, logs)
    deploy(lam, new)
    ok, smoke = smoke_test(lam)
    report = {"previous_image": previous, "new_image": new, "smoke_ok": ok, "smoke": smoke}
    if not ok:
        deploy(lam, previous)
        report["rolled_back"] = True
        report["after_rollback_ok"] = smoke_test(lam)[0]
    elif args.rollback_drill:
        t = time.time()
        deploy(lam, previous)
        report["drill_rollback_ok"] = smoke_test(lam)[0]
        deploy(lam, new)
        report["drill_roll_forward_ok"] = smoke_test(lam)[0]
        report["drill_seconds"] = round(time.time() - t)
    report["total_seconds"] = round(time.time() - t0)
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
