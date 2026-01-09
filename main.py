import os
import re
import time
import smtplib
import httpx
from email.message import EmailMessage
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

app = FastAPI()

# -------------------------
# ENV - WhatsApp
# -------------------------
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
WPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v24.0")

# -------------------------
# ENV - OpenAI
# -------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "Eres un asistente útil. Responde en español.")

# -------------------------
# ENV - Click to Call
# -------------------------
CLICK_TO_CALL = os.getenv("CLICK_TO_CALL", "")

# -------------------------
# ENV - Email Lead Notify (SMTP)
# -------------------------
LEAD_NOTIFY_EMAIL = os.getenv("LEAD_NOTIFY_EMAIL", "")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

# -------------------------
# Helpers: regex y keywords
# -------------------------
PHONE_RE = re.compile(r"(\+?\d[\d\s\-]{6,}\d)")
EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")

HUMAN_KEYWORDS = [
    "humano", "asesor", "agente", "persona", "vendedor", "ventas",
    "llamar", "llamada", "contactar", "quiero hablar", "quiero comunicarme"
]

PRICE_KEYWORDS = [
    "precio", "costo", "cuanto cuesta", "cotización", "cotizacion", "proforma"
]

# -------------------------
# Estado en memoria por wa_id
# En producción lo ideal es Redis/DB. Por ahora sirve.
# -------------------------
LEADS = {}  # wa_id -> dict


@app.get("/health")
def health():
    return {"status": "ok"}


# 1) Verificación Webhook Meta
@app.get("/webhook")
def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
        return PlainTextResponse(challenge, status_code=200)

    return PlainTextResponse("Forbidden", status_code=403)


# Enviar mensaje WhatsApp
async def send_whatsapp_text(to: str, text: str):
    if not (WPP_TOKEN and PHONE_NUMBER_ID):
        print("⚠️ Faltan WHATSAPP_TOKEN o WHATSAPP_PHONE_NUMBER_ID")
        return

    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WPP_TOKEN}", "Content-Type": "application/json"}
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


def is_price_intent(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in PRICE_KEYWORDS)


def extract_phone_email(text: str):
    phone = None
    email = None

    m1 = PHONE_RE.search(text or "")
    if m1:
        phone = m1.group(1).strip()

    m2 = EMAIL_RE.search(text or "")
    if m2:
        email = m2.group(1).strip()

    return phone, email


def get_lead(wa_id: str) -> dict:
    if wa_id not in LEADS:
        LEADS[wa_id] = {
            "wa_id": wa_id,
            "created_at": int(time.time()),
            "human_requested": False,
            "phone": None,
            "email": None,
            "name": None,
            "city": None,
            "last_intent": None,
            "email_sent": False,  # <- para NO enviar emails repetidos
        }
    return LEADS[wa_id]


def lead_log(lead: dict, reason: str = ""):
    print(
        "🟩 LEAD:",
        {
            "wa_id": lead.get("wa_id"),
            "phone": lead.get("phone"),
            "email": lead.get("email"),
            "name": lead.get("name"),
            "city": lead.get("city"),
            "human_requested": lead.get("human_requested"),
            "reason": reason,
        }
    )


def send_lead_email(lead: dict, last_user_message: str = ""):
    """
    Envía un email cuando hay un lead (teléfono/email) y el usuario pidió humano/cotización.
    """
    if not (LEAD_NOTIFY_EMAIL and SMTP_HOST and SMTP_USER and SMTP_PASS):
        print("⚠️ Email no configurado: faltan variables SMTP/LEAD_NOTIFY_EMAIL")
        return

    subject = f"Nuevo lead WhatsApp - {lead.get('wa_id')}"
    body = (
        "Nuevo lead capturado desde WhatsApp\n\n"
        f"wa_id: {lead.get('wa_id')}\n"
        f"Teléfono: {lead.get('phone')}\n"
        f"Email: {lead.get('email')}\n"
        f"Nombre: {lead.get('name')}\n"
        f"Ciudad: {lead.get('city')}\n"
        f"Human requested: {lead.get('human_requested')}\n"
        f"Último mensaje del cliente: {last_user_message}\n"
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = LEAD_NOTIFY_EMAIL
    msg.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        print("📧 Lead enviado por email a:", LEAD_NOTIFY_EMAIL)
    except Exception as e:
        print("❌ Error enviando email:", str(e))


async def ask_openai(user_text: str, lead: dict) -> str:
    if not OPENAI_API_KEY:
        return "⚠️ OpenAI no está configurado (falta OPENAI_API_KEY)."

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}

    internal_context = (
        f"Contexto interno (no lo muestres): wa_id={lead.get('wa_id')}, "
        f"phone={lead.get('phone')}, email={lead.get('email')}, "
        f"human_requested={lead.get('human_requested')}, "
        f"click_to_call={CLICK_TO_CALL or 'NO_DISPONIBLE'}.\n"
        "Regla: si phone/email ya existen, NO los vuelvas a pedir; solo confirma y avanza."
    )

    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": internal_context},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.3,
    }

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


def build_handoff_message(lead: dict) -> str:
    # Si ya tenemos teléfono o email, confirmamos y cerramos
    if lead.get("phone") or lead.get("email"):
        parts = ["Perfecto ✅ Ya tengo tus datos."]
        if CLICK_TO_CALL:
            parts.append(f"Si deseas hablar ahora con un asesor, puedes llamar aquí:\n{CLICK_TO_CALL}")
        parts.append("En breve un asesor se comunicará contigo. ¿En qué ciudad estás?")
        return "\n".join(parts)

    msg = (
        "Perfecto ✅ Un asesor puede ayudarte.\n"
        "Por favor compárteme:\n"
        "• Nombre\n"
        "• Ciudad\n"
        "• Teléfono o email\n"
    )
    if CLICK_TO_CALL:
        msg += f"\nTambién puedes llamar aquí:\n{CLICK_TO_CALL}"
    return msg


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
        from_number = msg.get("from")  # wa_id del cliente
        msg_type = msg.get("type")

        if not from_number:
            return {"status": "ok"}

        lead = get_lead(from_number)

        if msg_type != "text":
            await send_whatsapp_text(from_number, "Por ahora solo respondo mensajes de texto ✅")
            return {"status": "ok"}

        text_in = (msg.get("text", {}) or {}).get("body", "") or ""
        print(f"👤 From wa_id={from_number} text={text_in!r}")

        # 1) Capturar teléfono/email si vienen en el mensaje
        phone, email = extract_phone_email(text_in)
        if phone and not lead.get("phone"):
            lead["phone"] = phone
        if email and not lead.get("email"):
            lead["email"] = email

        # 2) Si el usuario pide humano/asesor → activar modo handoff
        if wants_human(text_in):
            lead["human_requested"] = True
            lead["last_intent"] = "human"
            lead_log(lead, reason="user_requested_human")

            # Si ya hay datos y aún no se envió email, lo enviamos
            lead_ready = (lead.get("phone") or lead.get("email"))
            if lead_ready and not lead.get("email_sent"):
                send_lead_email(lead, last_user_message=text_in)
                lead["email_sent"] = True

            await send_whatsapp_text(from_number, build_handoff_message(lead))
            return {"status": "ok"}

        # 3) Si detecta intención de precio/cotización: pedir datos mínimos y marcar intención
        if is_price_intent(text_in):
            lead["last_intent"] = "price"
            lead_log(lead, reason="price_intent")

            # Si ya hay datos y aún no se envió email, lo enviamos
            lead_ready = (lead.get("phone") or lead.get("email"))
            if lead_ready and not lead.get("email_sent"):
                send_lead_email(lead, last_user_message=text_in)
                lead["email_sent"] = True

            reply = (
                "Claro ✅ Para cotizar correctamente necesito 3 datos:\n"
                "• Modelo exacto (o qué estás buscando)\n"
                "• Cantidad de usuarios/extensiones (o capacidad)\n"
                "• Ciudad (para instalación/envío)\n\n"
                "Si quieres, también puedes dejar tu email y te envío la proforma."
            )
            if CLICK_TO_CALL:
                reply += f"\n\nSi deseas hablar ahora con un asesor:\n{CLICK_TO_CALL}"
            await send_whatsapp_text(from_number, reply)
            return {"status": "ok"}

        # 4) Si ya está en modo humano y manda datos → agradecer, enviar email (una sola vez) y no repetir
        if lead.get("human_requested") and (phone or email):
            lead_log(lead, reason="lead_data_received_after_handoff")

            if not lead.get("email_sent"):
                send_lead_email(lead, last_user_message=text_in)
                lead["email_sent"] = True

            await send_whatsapp_text(from_number, build_handoff_message(lead))
            return {"status": "ok"}

        # 5) Respuesta normal con OpenAI
        reply = await ask_openai(text_in, lead)
        await send_whatsapp_text(from_number, reply)

    except Exception as e:
        print("❌ Error:", str(e))

    return {"status": "ok"}

