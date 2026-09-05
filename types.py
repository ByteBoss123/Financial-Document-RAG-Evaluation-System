"""
types.py

Shared lightweight dataclasses used across the pipeline. Kept dependency-free
(no faiss, no sentence-transformers) so that failure_detection.py and its
tests can be imported and run without needing the heavy embedding/index
libraries installed -- those are only required by rag_index.py itself when
you actually build or query the index.
"""

from dataclasses import dataclass


@dataclass
class Chunk:
    chunk_id: int
    company: str
    form_type: str
    filed_date: str
    section_name: str
    source_url: str
    text: str
    fiscal_period_end: str = ""
