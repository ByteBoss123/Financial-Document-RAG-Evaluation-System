"""
rag_index.py

Chunks ingested filing sections, embeds them, and builds a FAISS index for
retrieval. This is the retrieval half of the RAG pipeline -- deliberately
kept simple (sentence-transformers + flat FAISS index) since the point of
this project is the failure-detection and observability layer on top, not
retrieval sophistication.
"""

import json
import logging
from pathlib import Path

import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

from app.types import Chunk

logger = logging.getLogger("findocqa.rag")

EMBED_MODEL_NAME = "all-MiniLM-L6-v2"  # small, fast, good enough for a demo-scale corpus
CHUNK_SIZE_CHARS = 1200
CHUNK_OVERLAP_CHARS = 200


def chunk_text(text: str, size: int = CHUNK_SIZE_CHARS, overlap: int = CHUNK_OVERLAP_CHARS) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


class FilingIndex:
    """
    Wraps a FAISS flat index + the sentence-transformer model + the chunk
    metadata needed to reconstruct what was retrieved (for logging and
    failure detection downstream).
    """

    def __init__(self):
        self.model = SentenceTransformer(EMBED_MODEL_NAME)
        self.index: faiss.Index | None = None
        self.chunks: list[Chunk] = []

    def build_from_data_dir(self, data_dir: str = "data"):
        records = []
        for path in Path(data_dir).glob("*.json"):
            with open(path) as f:
                records.extend(json.load(f))

        if not records:
            raise RuntimeError(
                f"No filing records found in {data_dir}. Run edgar_ingest.py first."
            )

        chunk_id = 0
        all_texts = []
        for rec in records:
            for piece in chunk_text(rec["text"]):
                self.chunks.append(Chunk(
                    chunk_id=chunk_id,
                    company=rec["company"],
                    form_type=rec["form_type"],
                    filed_date=rec["filed_date"],
                    section_name=rec["section_name"],
                    source_url=rec["source_url"],
                    text=piece,
                    fiscal_period_end=rec.get("fiscal_period_end") or "",
                ))
                all_texts.append(piece)
                chunk_id += 1

        logger.info(f"Embedding {len(all_texts)} chunks...")
        embeddings = self.model.encode(all_texts, show_progress_bar=False, normalize_embeddings=True)
        embeddings = np.asarray(embeddings, dtype="float32")

        dim = embeddings.shape[1]
        self.index = faiss.IndexFlatIP(dim)  # inner product on normalized vecs == cosine sim
        self.index.add(embeddings)
        logger.info(f"Index built: {self.index.ntotal} vectors, dim={dim}")

    def search(self, query: str, k: int = 4) -> list[tuple[Chunk, float]]:
        if self.index is None:
            raise RuntimeError("Index not built. Call build_from_data_dir() first.")
        q_emb = self.model.encode([query], normalize_embeddings=True)
        q_emb = np.asarray(q_emb, dtype="float32")
        scores, idxs = self.index.search(q_emb, k)
        results = []
        for score, idx in zip(scores[0], idxs[0]):
            if idx == -1:
                continue
            results.append((self.chunks[idx], float(score)))
        return results

    def save(self, path: str = "data/faiss_index"):
        Path(path).mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, f"{path}/index.faiss")
        with open(f"{path}/chunks.json", "w") as f:
            json.dump([c.__dict__ for c in self.chunks], f)

    def load(self, path: str = "data/faiss_index"):
        self.index = faiss.read_index(f"{path}/index.faiss")
        with open(f"{path}/chunks.json") as f:
            raw = json.load(f)
        self.chunks = [Chunk(**c) for c in raw]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    idx = FilingIndex()
    idx.build_from_data_dir()
    idx.save()
    print(f"Saved index with {len(idx.chunks)} chunks.")
