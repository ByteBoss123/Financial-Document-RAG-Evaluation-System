"""
observability.py

Structured logging for every QA request: what was asked, what was
retrieved, what the model answered, what failure checks fired, latency,
and token cost. This is the "logging and monitoring" half of the gap this
project is meant to close -- every request becomes one structured JSON
line, which the dashboard reads to compute rolling failure rates.

Deliberately uses plain JSON-lines logging rather than a heavier APM stack
(Datadog/Prometheus) so the project runs anywhere with zero infra setup --
but the log schema is designed so it could be piped into Prometheus/Grafana
or Datadog directly in a real deployment (see README for the swap-in note).
"""

import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# Lambda only permits writes under /tmp. Local runs retain the project-level
# logs directory unless FINDOCQA_LOG_DIR explicitly overrides it.
_default_log_dir = "/tmp/findocqa/logs" if os.environ.get("AWS_LAMBDA_FUNCTION_NAME") else "logs"
LOG_DIR = Path(os.environ.get("FINDOCQA_LOG_DIR", _default_log_dir))
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "requests.jsonl"

logger = logging.getLogger("findocqa.observability")
logging.basicConfig(level=logging.INFO)


@dataclass
class RequestLog:
    request_id: str
    timestamp: float
    question: str
    answer: str = ""
    retrieved_chunk_ids: list = field(default_factory=list)
    retrieved_scores: list = field(default_factory=list)
    top_score: Optional[float] = None
    latency_ms: Optional[float] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    failure_categories: list = field(default_factory=list)
    failure_details: list = field(default_factory=list)
    passed: Optional[bool] = None
    error: Optional[str] = None

    def to_jsonl(self) -> str:
        return json.dumps(asdict(self))


@contextmanager
def trace_request(question: str):
    """
    Usage:
        with trace_request(question) as rl:
            ... do retrieval, set rl.retrieved_chunk_ids etc ...
            ... do generation, set rl.answer ...
            rl.failure_categories = [...]
    Automatically records latency and writes the log line on exit, even if
    an exception occurs (with error captured) -- so failures don't disappear
    from the monitoring data, which is exactly the kind of silent gap this
    project is trying to eliminate.
    """
    rl = RequestLog(request_id=str(uuid.uuid4()), timestamp=time.time(), question=question)
    start = time.perf_counter()
    try:
        yield rl
    except Exception as e:
        rl.error = str(e)
        raise
    finally:
        rl.latency_ms = (time.perf_counter() - start) * 1000
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(rl.to_jsonl() + "\n")
        if rl.error:
            logger.error(f"[{rl.request_id}] failed: {rl.error}")
        else:
            status = "PASS" if rl.passed else "FLAGGED"
            logger.info(
                f"[{rl.request_id}] {status} latency={rl.latency_ms:.0f}ms "
                f"top_score={rl.top_score} flags={rl.failure_categories}"
            )


def load_logs() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    records = []
    with open(LOG_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records
