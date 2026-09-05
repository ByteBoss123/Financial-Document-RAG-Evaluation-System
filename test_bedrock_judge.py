from app.bedrock_judge import BedrockUnsupportedClaimJudge


class FakeBedrockClient:
    def __init__(self):
        self.request = None

    def converse(self, **kwargs):
        self.request = kwargs
        return {
            "output": {
                "message": {
                    "content": [{
                        "toolUse": {
                            "name": "record_claim_judgment",
                            "input": {
                                "supported": False,
                                "evidence": "No acquisition language",
                                "rationale": "The acquisition claim is absent.",
                            },
                        }
                    }]
                }
            }
        }


def test_bedrock_judge_parses_structured_result():
    client = FakeBedrockClient()
    judge = BedrockUnsupportedClaimJudge(client=client)
    result = judge("The company will acquire a rival.", "Revenue was stable.")
    assert result.supported is False
    assert result.evidence == "No acquisition language"
    assert client.request["inferenceConfig"]["maxTokens"] == 250
    assert client.request["toolConfig"]["toolChoice"]["tool"]["name"] == "record_claim_judgment"
