"""Amazon Bedrock judge for qualitative unsupported-claim detection."""

from __future__ import annotations

import json
from dataclasses import dataclass

@dataclass(frozen=True)
class ClaimJudgment:
    supported: bool
    evidence: str
    rationale: str


class BedrockUnsupportedClaimJudge:
    """Judge whether every material qualitative claim is supported by context."""

    TOOL_NAME = "record_claim_judgment"

    def __init__(
        self,
        model_id: str = "us.amazon.nova-lite-v1:0",
        region_name: str = "us-east-1",
        client=None,
    ) -> None:
        self.model_id = model_id
        if client is not None:
            self.client = client
        else:
            import boto3
            from botocore.config import Config

            self.client = boto3.client(
                "bedrock-runtime",
                region_name=region_name,
                config=Config(
                    retries={"total_max_attempts": 5, "mode": "adaptive"},
                    connect_timeout=5,
                    read_timeout=30,
                ),
            )

    def __call__(self, answer: str, context: str) -> ClaimJudgment:
        response = self.client.converse(
            modelId=self.model_id,
            system=[{
                "text": (
                    "You are a strict financial QA evaluator. Determine whether every "
                    "material qualitative claim in the answer is explicitly supported "
                    "by the supplied context. Do not use outside knowledge."
                )
            }],
            messages=[{
                "role": "user",
                "content": [{"text": f"CONTEXT:\n{context}\n\nANSWER:\n{answer}"}],
            }],
            inferenceConfig={"maxTokens": 250, "temperature": 0},
            toolConfig={
                "tools": [{
                    "toolSpec": {
                        "name": self.TOOL_NAME,
                        "description": "Return the groundedness judgment.",
                        "inputSchema": {
                            "json": {
                                "type": "object",
                                "properties": {
                                    "supported": {"type": "boolean"},
                                    "evidence": {"type": "string"},
                                    "rationale": {"type": "string"},
                                },
                                "required": ["supported", "evidence", "rationale"],
                            }
                        },
                    }
                }],
                "toolChoice": {"tool": {"name": self.TOOL_NAME}},
            },
            requestMetadata={"application": "findocqa", "stage": "unsupported-claim-judge"},
        )

        for block in response["output"]["message"]["content"]:
            use = block.get("toolUse")
            if use and use.get("name") == self.TOOL_NAME:
                payload = use["input"]
                return ClaimJudgment(
                    supported=bool(payload["supported"]),
                    evidence=str(payload["evidence"]),
                    rationale=str(payload["rationale"]),
                )
        raise ValueError("Bedrock judge returned no structured tool result: " + json.dumps(response))
