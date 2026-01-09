import os
import json
import re
import httpx
from bs4 import BeautifulSoup

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

DEFAULT_URLS = [
    "https://nuxway.net/",
    "https://nuxway.net/quienes-somos",
    "https://nuxway.net/soluciones",
    "https://nuxway.net/productos",
    "https://nuxway.services/",
]

def clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()

def chunk_text(text: str, max_chars: int = 1200, overlap: int = 200):
    chunks = []
    i = 0
    n = len(text)
    step = max_chars - overlap
    if step <= 0:
        step = max_chars
    while i < n:
        chunk = text[i:i+max_chars].strip()
        if chunk:
            chunks.append(chunk)
        i += step
    return chunks

async def fetch_url(client: httpx.AsyncClient, url: str) -> str:
    r = await client.get(url, follow_redirects=True, timeout=30)
    r.raise_for_status()
    return r.text

async def embed_texts(texts):
    if not OPENAI_API_KEY:
        raise RuntimeError("Falta OPENAI_API_KEY para generar embeddings.")

    url = "https://api.openai.com/v1/embeddings"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}

    embeddings = []
    async with httpx.AsyncClient(timeout=60) as client:
        batch_size = 64
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            payload = {"model": OPENAI_EMBED_MODEL, "input": batch}
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            for item in data["data"]:
                embeddings.append(item["embedding"])
    return embeddings

async def main():
    urls_env = os.getenv("KNOWLEDGE_URLS", "").strip()
    urls = [u.strip() for u in urls_env.split(",") if u.strip()] if urls_env else DEFAULT_URLS

    docs = []
    async with httpx.AsyncClient() as client:
        for url in urls:
            print("Descargando:", url)
            try:
                html = await fetch_url(client, url)
                text = clean_text(html)
                if len(text) < 200:
                    print("⚠️ Muy poco texto, saltando:", url)
                    continue
                chunks = chunk_text(text)
                for c in chunks:
                    docs.append({"source": url, "text": c})
            except Exception as e:
                print("❌ Error:", url, str(e))

    print("Total chunks:", len(docs))
    texts = [d["text"] for d in docs]

    print("Generando embeddings...")
    embs = await embed_texts(texts)

    for d, e in zip(docs, embs):
        d["embedding"] = e

    out = {"version": 1, "docs": docs}
    with open("knowledge_store.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)

    print("✅ Guardado knowledge_store.json con", len(docs), "chunks")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

