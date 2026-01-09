import os
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

app = FastAPI()

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
WPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v24.0")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "Eres un asistente útil. Responde en español.")


@app.get("/health")
def health():
    return {"status": "ok"}


# Verificación webhook (Meta)
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
        "text": {"body": text[:3500]},  # limite seguro
    }

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(url, headers=headers, json=payload)
        print("📤 Send status:", r.status_code, r.text)


async def ask_openai(user_text: str) -> str:
    if not OPENAI_API_KEY:
        return "⚠️ OpenAI no está configurado todavía (falta OPENAI_API_KEY)."

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.3,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=headers, json=payload)

    if r.status_code != 200:
        print("❌ OpenAI error:", r.status_code, r.text)
        return "Tuve un problema al generar la respuesta. ¿Puedes intentar de nuevo en un momento?"

    data = r.json()
    return (data["choices"][0]["message"]["content"] or "").strip() or "¿Me das un poco más de detalle?"


@app.post("/webhook")
async def receive_webhook(request: Request):
    body = await request.json()
    print("📩 Webhook recibido:", body)

    try:
        entry = body.get("entry", [])[0]
        change = entry.get("changes", [])[0]
        value = change.get("value", {})

        messages = value.get("messages", [])
        if not messages:
            return {"status": "ok"}

        msg = messages[0]
        from_number = msg.get("from")
        msg_type = msg.get("type")

        if not from_number:
            return {"status": "ok"}

        if msg_type == "text":
            text_in = msg.get("text", {}).get("body", "")
            reply = await ask_openai(text_in)
        else:
            reply = "Por ahora solo puedo responder mensajes de texto ✅"

        await send_whatsapp_text(from_number, reply)

    except Exception as e:
        print("❌ Error:", str(e))

    return {"status": "ok"}


