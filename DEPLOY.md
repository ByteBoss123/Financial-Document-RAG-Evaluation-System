# Deploying FinDocQA to AWS Lambda

No changes were made to `app/main.py` or any existing FinDocQA source —
this only adds a deployment layer on top.

## Why container-image Lambda, not zip

`sentence-transformers` pulls in `torch`, which alone exceeds the 250MB
zip-based Lambda package limit. This uses `PackageType: Image` instead,
which supports images up to 10GB via ECR.

## What gets baked in at build time

The Dockerfile runs `edgar_ingest.py` and `rag_index.py` during the
image build, so the FAISS index for BGC/JPM/GS/MS/ICE filings is already
present at cold start — no live EDGAR calls or embedding work happens
per-invocation. To index different companies, edit the `RUN python -m
app.edgar_ingest ...` line in the Dockerfile.

## Steps (run from this directory)

```bash
# 1. Build and test the container locally first
docker build -t findocqa .
docker run -p 9000:8080 findocqa
# In another terminal:
curl -XPOST "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -d '{"httpMethod":"GET","path":"/health"}'

# 2. Deploy via SAM (builds + pushes to ECR + creates Lambda + API Gateway)
sam build
sam deploy --guided
#   - Confirm "Image" package type when prompted
#   - SAM creates an ECR repo automatically if none exists
#   - Note the ApiUrl output at the end -- that's your public endpoint
```

The SAM template sets `FINDOCQA_LOG_DIR=/tmp/findocqa/logs`, because Lambda's
deployment filesystem is read-only outside `/tmp`. It also grants the function
least-privilege `bedrock:InvokeModel` access for the configured Nova Lite judge.

After deployment, verify all three endpoints rather than treating stack
creation as proof that the application works:

```bash
curl "$ApiUrl/health"
curl -X POST "$ApiUrl/ask" -H "Content-Type: application/json" \
  -d '{"question":"What risks did the filing identify?"}'
curl "$ApiUrl/logs"
```

## Setting ANTHROPIC_API_KEY (optional)

Without it, `app/main.py` already falls back to an extractive answer
(no code change needed — this is existing behavior, not something added
for deployment). To enable real generation:

```bash
aws secretsmanager create-secret \
  --name findocqa/anthropic-api-key \
  --secret-string "sk-ant-..."
```
Then pass the resulting secret ARN as `AnthropicApiKeySecretArn` in
`sam deploy --guided`, and set the Lambda's environment variable
`ANTHROPIC_API_KEY` to pull from it (via a small init step, or Lambda's
native Secrets Manager environment variable integration).

## IAM scope

The SAM template only grants `secretsmanager:GetSecretValue` on the one
named secret ARN — nothing broader. No other AWS permissions are needed
for this function; it doesn't touch S3, DynamoDB, or anything else.

## Cost note

`MemorySize: 1024` and `Timeout: 30` are conservative starting points
for a `sentence-transformers` model load + FAISS search + one Anthropic
API call per request. Watch actual invocation duration in CloudWatch
after a few real requests and tune down if it's consistently fast.
