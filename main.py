import os
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

app = FastAPI()

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
WPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v21.0")


@app.get("/health")
def health():
    return {"status": "ok"}


# 1) Verificación de webhook (Meta)
@app.get("/webhook")
def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
        return PlainTextResponse(challenge, status_code=200)

    return PlainTextResponse("Forbidden", status_code=403)


# Helper: enviar mensaje a WhatsApp
async def send_whatsapp_text(to: str, text: str):
    if not (WPP_TOKEN and PHONE_NUMBER_ID):
        # Si faltan variables, no revienta; solo loguea.
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
        "text": {"body": text},
    }

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, headers=headers, json=payload)
        print("📤 Send status:", r.status_code, r.text)


# 2) Recibir mensajes (Meta)
@app.post("/webhook")
async def receive_webhook(request: Request):
    body = await request.json()
    print("📩 Webhook recibido:", body)

    # Extraer mensaje de texto si existe
    try:
        entry = body.get("entry", [])[0]
        change = entry.get("changes", [])[0]
        value = change.get("value", {})

        messages = value.get("messages", [])
        if not messages:
            return {"status": "ok"}  # pueden llegar statuses y otros eventos

        msg = messages[0]
        from_number = msg.get("from")  # número del usuario
        msg_type = msg.get("type")

        # Solo respondemos texto por ahora
        if msg_type == "text":
            text_in = msg.get("text", {}).get("body", "")
            reply = f"Hola, recibido ✅\nDijiste: {text_in}"
        else:
            reply = "Por ahora solo puedo responder texto ✅"

        if from_number:
            await send_whatsapp_text(from_number, reply)

    except Exception as e:
        print("❌ Error parseando webhook:", str(e))

    return {"status": "ok"}

