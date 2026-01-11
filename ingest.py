import os
import json
import re
import httpx
from bs4 import BeautifulSoup

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

DEFAULT_URLS = [
    "https://www.nuxway.net/",
    "https://www.nuxway.net/soluciones",
    # "https://www.nuxway.net/productos",  # bloquea por 429, luego lo vemos
    "https://nuxway.services/",
]


CATALOG_FILES = [
    "catalogo_yeastar.md"
]

def clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def chunk_text(text, size=1200, overlap=200):
    chunks = []
    i = 0
    while i < len(text):
        chunks.append(text[i:i+size])
        i += size - overlap
    return chunks

async def fetch_url(client, url):
    r = await client.get(url, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r.text


async def embed(texts):
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    url = "https://api.openai.com/v1/embeddings"
    embs = []
    async with httpx.AsyncClient() as client:
        for i in range(0, len(texts), 64):
            batch = texts[i:i+64]
            r = await client.post(url, headers=headers, json={
                "model": OPENAI_EMBED_MODEL,
                "input": batch
            })
            r.raise_for_status()
            for d in r.json()["data"]:
                embs.append(d["embedding"])
    return embs

async def main():
    docs = []

    async with httpx.AsyncClient() as client:
        for url in DEFAULT_URLS:
            try:
                html = await fetch_url(client, url)
                text = clean_text(html)
                for c in chunk_text(text):
                    docs.append({"source": url, "text": c})
            except Exception as e:
                print("Error URL:", url, e)

    for file in CATALOG_FILES:
        if os.path.exists(file):
            with open(file, "r", encoding="utf-8") as f:
                text = f.read()
            for c in chunk_text(text):
                docs.append({"source": file, "text": c})

    texts = [d["text"] for d in docs]
    embeddings = await embed(texts)

    for d, e in zip(docs, embeddings):
        d["embedding"] = e

    with open("knowledge_store.json", "w", encoding="utf-8") as f:
        json.dump({"docs": docs}, f, ensure_ascii=False)

    print("knowledge_store.json generado con", len(docs), "chunks")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

