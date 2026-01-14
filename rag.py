import json
import os
import numpy as np
import httpx

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
STORE_PATH = os.getenv("KNOWLEDGE_STORE_PATH", "knowledge_store.json")

def load_store():
    if not os.path.exists(STORE_PATH):
        raise FileNotFoundError(
            f"No existe {STORE_PATH}. Genera knowledge_store.json con ingest.py y súbelo al repo."
        )

    with open(STORE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    docs = data.get("docs", [])
    texts = [d["text"] for d in docs]
    sources = [d.get("source", "") for d in docs]
    embs = np.array([d["embedding"] for d in docs], dtype=np.float32)

    norms = np.linalg.norm(embs, axis=1, keepdims=True) + 1e-12
    embs = embs / norms
    return texts, sources, embs

async def embed_query(query: str):
    if not OPENAI_API_KEY:
        raise RuntimeError("Falta OPENAI_API_KEY para embeddings.")

    url = "https://api.openai.com/v1/embeddings"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": OPENAI_EMBED_MODEL, "input": query}

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()

    emb = np.array(data["data"][0]["embedding"], dtype=np.float32)
    emb = emb / (np.linalg.norm(emb) + 1e-12)
    return emb

async def retrieve(query: str, k: int = 5):
    texts, sources, embs = load_store()
    q = await embed_query(query)
    sims = embs @ q
    top_idx = np.argsort(-sims)[:k]
    results = []
    for i in top_idx:
        results.append({
            "score": float(sims[i]),
            "source": sources[i],
            "text": texts[i],
        })
    return results
