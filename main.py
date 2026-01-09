import os
import re
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from rag import retrieve

app = FastAPI()

# WhatsApp
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
WPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v24.0")

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "Eres un asistente de ventas. Responde en español.")

CLICK_TO_CALL = os.getenv(
    "CLICK_TO_CALL",
    "https://nuxwaytechnology.use.ycmcloud.com/webtrunk/calllink?code=OVp4MjY0R0I0SjBPc2VEUXN0MTFRT2ZZZVN3TFd0QXM="
)

HUMAN_KEYWORDS = [
    "humano", "asesor", "agente", "persona", "llamar", "llamada", "contactar", "vendedor", "ventas"
]

PHONE_RE = re.compile(r"(\+?\d[\d\s\-]{6,}\d)")
EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/webhook")
def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
        return PlainTextResponse(challenge, status_code=200)

    return PlainTextResponse("Forbidden", status_code=403)

async def send_whatsapp_text(to: str, text: str):
    if not (WPP_TOKEN and PHONE_NUMBER_ID):
        print("⚠️ Faltan WHATSAPP_TOKEN o WHATSAPP_PHONE_NUMBER_ID")
        return

    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text[:3500]},
    }

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(url, headers=headers, json=payload)
        print("📤 Send status:", r.status_code, r.text)

def wants_human(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in HUMAN_KEYWORDS)

def extract_lead(text: str):
    phone = None
    email = None

    m = PHONE_RE.search(text or "")
    if m:
        phone = m.group(1).strip()

    m2 = EMAIL_RE.search(text or "")
    if m2:
        email = m2.group(1).strip()

    return phone, email

async def ask_openai_with_rag(user_text: str) -> str:
    if not OPENAI_API_KEY:
        return "⚠️ OpenAI no está configurado (falta OPENAI_API_KEY)."

    # 1) RAG: busca contexto web
    try:
        hits = await retrieve(user_text, k=5)
    except Exception as e:
        print("⚠️ RAG error:", str(e))
        hits = []

    context_blocks = []
    for h in hits:
        context_blocks.append(
            f"Fuente: {h['source']}\nContenido:\n{h['text']}"
        )
    rag_context = "\n\n---\n\n".join(context_blocks) if context_blocks else "Sin contexto adicional."

    # 2) Llamada a OpenAI (chat completions)
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"Contexto extraído de sitios de Nuxway. Úsalo si es relevante y no inventes:\n\n{rag_context}"},
        {"role": "user", "content": user_text},
    ]

    payload = {"model": OPENAI_MODEL, "messages": messages, "temperature": 0.3}

    print("🤖 OpenAI input:", user_text)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=headers, json=payload)

    if r.status_code != 200:
        print("❌ OpenAI error:", r.status_code, r.text)
        return "Tuve un problema al generar la respuesta. ¿Puedes intentar de nuevo?"

    data = r.json()
    out = (data["choices"][0]["message"]["content"] or "").strip()
    print("🤖 OpenAI output:", out[:400])
    return out or "¿Me das un poco más de detalle?"

@app.post("/webhook")
async def receive_webhook(request: Request):
    body = await request.json()
    # print completo para debug
    print("📩 Webhook recibido:", body)

    try:
        entry = body.get("entry", [])[0]
        change = entry.get("changes", [])[0]
        value = change.get("value", {})

        messages = value.get("messages", [])
        if not messages:
            return {"status": "ok"}

        msg = messages[0]
        from_number = msg.get("from")  # wa_id del cliente
        msg_type = msg.get("type")

        if not from_number:
            return {"status": "ok"}

        if msg_type != "text":
            await send_whatsapp_text(from_number, "Por ahora solo respondo mensajes de texto ✅")
            return {"status": "ok"}

        text_in = msg.get("text", {}).get("body", "") or ""
        print(f"👤 From wa_id={from_number} text={text_in!r}")

        # Si pide humano: enfoque ventas + captura de lead
        if wants_human(text_in):
            reply = (
                "Perfecto ✅\n"
                "Para que un asesor te contacte, ¿me compartes estos datos?\n"
                "• Nombre\n• Ciudad\n• Empresa (opcional)\n• Teléfono o email\n\n"
                f"También puedes llamar aquí: {CLICK_TO_CALL}"
            )
            await send_whatsapp_text(from_number, reply)
            return {"status": "ok"}

        # Si manda teléfono/email, loguear lead (aunque sea parcial)
        phone, email = extract_lead(text_in)
        if phone or email:
            print(f"🟩 LEAD capturado: wa_id={from_number} phone={phone} email={email}")

        # Respuesta normal usando RAG + OpenAI
        reply = await ask_openai_with_rag(text_in)
        await send_whatsapp_text(from_number, reply)

    except Exception as e:
        print("❌ Error:", str(e))

    return {"status": "ok"}


