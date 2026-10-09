FROM public.ecr.aws/lambda/python:3.12

WORKDIR ${LAMBDA_TASK_ROOT}
COPY requirements-api.txt .
RUN pip install --no-cache-dir --prefer-binary torch==2.3.1 --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir --prefer-binary -r requirements-api.txt

# Bake the embedding model into the image so cold starts do not download it into /tmp.
ENV SENTENCE_TRANSFORMERS_HOME=/opt/models HF_HOME=/opt/models
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY app ./app
ARG EDGAR_USER_AGENT
ENV EDGAR_USER_AGENT=${EDGAR_USER_AGENT}
# Pull the latest 10-K for each filer and build the FAISS index at build time.
RUN python -m app.edgar_ingest BGC JPM GS MS ICE \
 && python -c "import json,glob; [print('INGESTED', f, len(json.load(open(f)))) for f in sorted(glob.glob('data/*.json'))]" \
 && python -m app.rag_index

ENV FINDOCQA_LOG_DIR=/tmp/findocqa/logs HF_HUB_OFFLINE=1
CMD ["app.lambda_handler.handler"]
