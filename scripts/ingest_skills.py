"""
DuckClaw — Skill Knowledge Base Ingestion Script.

Run this once (and re-run whenever skills are added/updated) to populate
ChromaDB with skill metadata so the orchestrator can do semantic skill lookup.

Usage:
    python scripts/ingest_skills.py

Skill definitions live in duckclaw/skills/knowledge_base.py.
"""

import sys
import os

# Allow running from repo root without installing the package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chromadb
from chromadb.config import Settings

from duckclaw.skills.knowledge_base import SKILLS


def ingest(chroma_path: str = "~/.duckclaw/chroma_db"):
    resolved = os.path.expanduser(chroma_path)
    os.makedirs(resolved, exist_ok=True)

    client = chromadb.PersistentClient(
        path=resolved,
        settings=Settings(anonymized_telemetry=False),
    )
    collection = client.get_or_create_collection(
        name="duckclaw_skills",
        metadata={"hnsw:space": "cosine"},
    )

    existing = collection.get()
    if existing["ids"]:
        collection.delete(ids=existing["ids"])
        print(f"Cleared {len(existing['ids'])} existing skill entries.")

    ids, documents, metadatas = [], [], []
    for skill in SKILLS:
        search_doc = skill["description"]
        if skill.get("use_cases"):
            search_doc += "\nExample queries: " + "; ".join(skill["use_cases"])
        ids.append(skill["skill_id"])
        documents.append(search_doc)
        metadatas.append({
            "skill_id": skill["skill_id"],
            "name": skill["name"],
            "input_format": skill.get("input_format", ""),
            "output_format": skill.get("output_format", ""),
        })

    collection.add(ids=ids, documents=documents, metadatas=metadatas)
    print(f"✅ Ingested {len(SKILLS)} skills into ChromaDB at {resolved}")
    for skill in SKILLS:
        print(f"   • {skill['name']} ({skill['skill_id']})")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ingest DuckClaw skill metadata into ChromaDB.")
    parser.add_argument(
        "--chroma-path",
        default="~/.duckclaw/chroma_db",
        help="Path to the ChromaDB persistent storage directory (default: ~/.duckclaw/chroma)",
    )
    args = parser.parse_args()
    ingest(args.chroma_path)
