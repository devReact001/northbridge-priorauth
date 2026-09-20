"""Ingest policy PDFs into Postgres.

Run from the backend/ folder (venv active, database running):
    python -m app.rag.ingest --reset
"""

import argparse
from pathlib import Path

from . import store
from .chunking import chunk_directory
from .embedder import get_embedder

DEFAULT_PDF_DIR = Path(__file__).resolve().parents[3] / "policies" / "pdf"


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest policy PDFs into pgvector")
    parser.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_DIR)
    parser.add_argument("--embedder", default="local", help="local | hashing")
    parser.add_argument("--reset", action="store_true", help="drop and recreate the policy_chunks table")
    args = parser.parse_args()

    chunks = chunk_directory(args.pdf_dir)
    if not chunks:
        raise SystemExit(f"No chunks found in {args.pdf_dir}. Did you run scripts/make_policy_pdfs.py?")
    print(f"Chunked {len(chunks)} sections from {args.pdf_dir}")

    embedder = get_embedder(args.embedder)
    print(f"Embedding with {embedder.name} (first run downloads the model)...")
    vectors = embedder.embed_documents([c.text for c in chunks])

    with store.connect() as conn:
        if args.reset:
            store.reset_schema(conn, embedder.dim)
        store.insert_chunks(conn, chunks, vectors, embedder.name)
    print(f"Stored {len(chunks)} chunks.")


if __name__ == "__main__":
    main()
