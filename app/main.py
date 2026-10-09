"""
main.py

FastAPI service exposing the FinDocQA pipeline: ask a question about a
company's SEC filings, get an answer grounded in retrieved chunks, with
every request automatically logged and checked against the failure-mode
taxonomy before the response is returned.

Run:
    uvicorn app.main:app --reload --port 8000

Then POST to /ask:
    curl -X POST localhost:8000/ask \
         -H "Content-Type: application/json" \
         -d '{"question": "What are BGC Group main risk factors related to AI?"}'
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.rag_index import FilingIndex
from app.failure_detection import evaluate_response
from app.answer_format import clip as _clip
from app.observability import trace_request, load_logs
from app.bedrock_judge import BedrockUnsupportedClaimJudge

logger = logging.getLogger("findocqa.api")

# Global index, loaded once at startup rather than per-request.
_index: FilingIndex | None = None
_unsupported_claim_judge = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _index, _unsupported_claim_judge
    _index = FilingIndex()
    try:
        _index.load("data/faiss_index")
        logger.info(f"Loaded index with {len(_index.chunks)} chunks.")
    except FileNotFoundError:
        logger.warning(
            "No saved index found at data/faiss_index. "
            "Run `python -m app.edgar_ingest` then `python -m app.rag_index` first."
        )
    if os.environ.get("ENABLE_BEDROCK_JUDGE", "false").lower() == "true":
        _unsupported_claim_judge = BedrockUnsupportedClaimJudge(
            model_id=os.environ.get("BEDROCK_JUDGE_MODEL_ID", "us.amazon.nova-lite-v1:0"),
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )
    yield


app = FastAPI(title="FinDocQA", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000)
    top_k: int = Field(default=4, ge=1, le=10)


class AskResponse(BaseModel):
    request_id: str
    answer: str
    passed: bool
    failure_categories: list[str]
    sources: list[dict]


SYSTEM_PROMPT = (
    "You are a financial document QA assistant. Answer ONLY using the provided source excerpts. "
    "Always state which company and filing your answer comes from. If the excerpts don't contain "
    "the answer, say so explicitly rather than guessing."
)
_bedrock_client = None


def _bedrock_answer(question: str, context_block: str, model_id: str) -> str:
    """Generate with Amazon Bedrock (Converse API), using the Lambda's IAM role; no API key needed."""
    global _bedrock_client
    try:
        if _bedrock_client is None:
            import boto3
            _bedrock_client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        resp = _bedrock_client.converse(
            modelId=model_id,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": f"Sources:\n{context_block}\n\nQuestion: {question}"}]}],
            inferenceConfig={"maxTokens": 400, "temperature": 0},
        )
        return resp["output"]["message"]["content"][0]["text"]
    except Exception as e:  # noqa: BLE001 - surface any provider error in the logged answer
        logger.error(f"Bedrock generation failed: {e}")
        return f"[generation error: {e}]"


def generate_answer(question: str, context_chunks: list[tuple]) -> str:
    """
    Calls the Anthropic API to generate a grounded answer from retrieved
    context. Requires ANTHROPIC_API_KEY to be set in the environment.
    Falls back to an extractive stub if no key is present, so the service
    is still runnable/demoable without API access.
    """
    context_block = "\n\n---\n\n".join(
        f"[Source: {c.company}, {c.form_type} filed {c.filed_date}, section: {c.section_name}]\n{c.text}"
        for c, _ in context_chunks
    )

    bedrock_model = os.environ.get("BEDROCK_GENERATION_MODEL_ID")
    if bedrock_model:
        return _bedrock_answer(question, context_block, bedrock_model)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        top_chunk = context_chunks[0][0]
        return (
            f"[NO API KEY SET -- extractive fallback] Based on {top_chunk.company}'s "
            f"{top_chunk.form_type} ({top_chunk.section_name} section): "
            f"{_clip(top_chunk.text)}..."
        )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            system=(
                "You are a financial document QA assistant. Answer ONLY using the "
                "provided source excerpts. Always state which company and filing "
                "your answer comes from. If the excerpts don't contain the answer, "
                "say so explicitly rather than guessing."
            ),
            messages=[{
                "role": "user",
                "content": f"Sources:\n{context_block}\n\nQuestion: {question}",
            }],
        )
        return response.content[0].text
    except Exception as e:
        logger.error(f"Generation failed: {e}")
        return f"[generation error: {e}]"


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    if _index is None or _index.index is None:
        raise HTTPException(
            status_code=503,
            detail="Index not loaded. Run ingestion and indexing scripts first.",
        )

    with trace_request(req.question) as rl:
        retrieved = _index.search(req.question, k=req.top_k)
        rl.retrieved_chunk_ids = [c.chunk_id for c, _ in retrieved]
        rl.retrieved_scores = [s for _, s in retrieved]
        rl.top_score = retrieved[0][1] if retrieved else None

        answer = generate_answer(req.question, retrieved)
        rl.answer = answer

        eval_result = evaluate_response(
            req.question,
            answer,
            retrieved,
            unsupported_claim_judge=_unsupported_claim_judge,
        )
        rl.failure_categories = eval_result.categories
        rl.failure_details = [f.detail for f in eval_result.flags]
        rl.passed = eval_result.passed

        sources = [
            {
                "company": c.company,
                "form_type": c.form_type,
                "filed_date": c.filed_date,
                "section": c.section_name,
                "similarity": round(score, 3),
                "source_url": c.source_url,
            }
            for c, score in retrieved
        ]

        return AskResponse(
            request_id=rl.request_id,
            answer=answer,
            passed=eval_result.passed,
            failure_categories=eval_result.categories,
            sources=sources,
        )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "index_loaded": _index is not None and _index.index is not None,
        "chunk_count": len(_index.chunks) if _index else 0,
        "unsupported_claim_judge_enabled": _unsupported_claim_judge is not None,
    }


@app.get("/logs")
def get_logs(limit: int = 50):
    logs = load_logs()
    return {"count": len(logs), "logs": logs[-limit:]}
