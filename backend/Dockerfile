# Build from the project root:  docker build -t northbridge/api:local -f backend/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf \
    HOME=/tmp

WORKDIR /srv

# Dependencies first, so a code change does not reinstall them. CPU-only torch: the default wheel bundles CUDA
# libraries and adds about 2 GB to an image that never sees a GPU.
COPY backend/requirements.txt backend/requirements-rag.txt ./
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements.txt -r requirements-rag.txt

# The two retrieval models are baked into the image, so a pod starts without internet access to a model hub and a
# restart never waits on a download. These names must match app/rag/embedder.py and reranker.py; a test checks it.
RUN python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer('BAAI/bge-small-en-v1.5'); CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"
ENV HF_HUB_OFFLINE=1

COPY backend/app ./app
COPY policies/pdf ./policies/pdf

# Not root. Everything the process writes (temp files, the outbox volume) is mounted or under /tmp.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
USER 10001

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
