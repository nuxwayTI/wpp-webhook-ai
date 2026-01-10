import os
import re
import time
import httpx
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
# ENV - Webs (nuevo)
# -------------------------
NUXWAY_WEB = os.getenv("NUXWAY_WEB", "https://nuxway.net")
NUXWAY_SERVICES_WEB = os.getenv("NUXWAY_SERVICES_WEB", "https://nuxway.services")

# -------------------------
# CONTACTO OFICIAL (REAL)
# -------------------------
NUXWAY_PHONE_MOBILE = "(+591) 617 86583"
NUXWAY_PHONE_LANDLINE = "(+591) 4 483862"
NUXWAY_EMAIL_SALES = "ventas@nuxway.net"

# -------------------------
# Helpers: regex y keywords
# -------------------------
PHONE_RE = re.compile(r"(\+?\d[\d\s\-]{6,}\d)")
EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")

HUMAN_KEYWORDS = [
    "humano", "asesor", "agente", "persona", "vendedor", "ventas",
    "quiero hablar", "quiero comunicarme", "quiero un asesor", "hablar con alguien"
]

PRICE_KEYWORDS = [
    "precio", "costo", "cuanto cuesta", "cuánto cuesta", "cotización", "cotizacion", "proforma"
]

CLICK_LINK_KEYWORDS = [
    "click to call", "clicktocall", "call link", "calllink",
    "enlace", "link", "url", "llamar", "llamada", "llamada directa", "botón", "boton"
]

# -------------------------
# Estado en memoria por wa_id
# -------------------------
LEADS = {}  # wa_id -> dict


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


def wants_click_to_call(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in CLICK_LINK_KEYWORDS)


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


def contact_pack() -> str:
    parts = []
    if CLICK_TO_CALL:
        parts.append(f"📲 Click to Call (hablar con asesor):\n{CLICK_TO_CALL}")
    parts.append(
        "📞 Teléfonos:\n"
        f"• Móvil: {NUXWAY_PHONE_MOBILE}\n"
        f"• Fijo: {NUXWAY_PHONE_LANDLINE}\n"
        f"📧 Email: {NUXWAY_EMAIL_SALES}"
    )
    parts.append(
        "🌐 Web:\n"
        f"• {NUXWAY_WEB}\n"
        f"• {NUXWAY_SERVICES_WEB}"
    )
    return "\n\n".join(parts)


def build_handoff_message(lead: dict) -> str:
    if lead.get("phone") or lead.get("email"):
        return (
            "Perfecto ✅ Ya tengo tus datos.\n\n"
            f"{contact_pack()}\n\n"
            "En breve un asesor se comunicará contigo. ¿En qué ciudad estás?"
        )

    return (
        "Perfecto ✅ Un asesor puede ayudarte.\n"
        "Por favor compárteme:\n"
        "• Nombre\n"
        "• Ciudad\n"
        "• Teléfono o email\n\n"
        f"{contact_pack()}"
    )


async def ask_openai(user_text: str, lead: dict) -> str:
    if not OPENAI_API_KEY:
        return "⚠️ OpenAI no está configurado (falta OPENAI_API_KEY)."

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}

    internal_context = (
        f"Contexto interno (no lo muestres): wa_id={lead.get('wa_id')}, "
        f"phone={lead.get('phone')}, email={lead.get('email')}, human_requested={lead.get('human_requested')}.\n"
        "Regla: si phone/email ya existen, NO los vuelvas a pedir; confirma y avanza."
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

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=headers, json=payload)

    if r.status_code != 200:
        print("❌ OpenAI error:", r.status_code, r.text)
        return "Tuve un problema al generar la respuesta. ¿Puedes intentar de nuevo?"

    data = r.json()
    out = (data["choices"][0]["message"]["content"] or "").strip()
    return out or "¿Me das un poco más de detalle?"


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

        lead = get_lead(from_number)

        if msg_type != "text":
            await send_whatsapp_text(from_number, "Por ahora solo respondo mensajes de texto ✅")
            return {"status": "ok"}

        text_in = (msg.get("text", {}) or {}).get("body", "") or ""
        print(f"👤 From wa_id={from_number} text={text_in!r}")

        phone, email = extract_phone_email(text_in)
        if phone and not lead.get("phone"):
            lead["phone"] = phone
        if email and not lead.get("email"):
            lead["email"] = email

        # Si pide click-to-call/link/llamada -> dar paquete completo
        if wants_click_to_call(text_in):
            await send_whatsapp_text(
                from_number,
                "Claro ✅ Aquí tienes las opciones para comunicarte con un asesor:\n\n" + contact_pack()
            )
            return {"status": "ok"}

        # Si pide humano -> dar paquete completo
        if wants_human(text_in):
            lead["human_requested"] = True
            lead["last_intent"] = "human"
            lead_log(lead, reason="user_requested_human")
            await send_whatsapp_text(from_number, build_handoff_message(lead))
            return {"status": "ok"}

        # Si ya está en modo humano y manda datos -> confirmar y paquete completo
        if lead.get("human_requested") and (phone or email):
            lead_log(lead, reason="lead_data_received_after_handoff")
            await send_whatsapp_text(from_number, build_handoff_message(lead))
            return {"status": "ok"}

        # Si pide precio -> pedir datos + paquete completo
        if is_price_intent(text_in):
            lead["last_intent"] = "price"
            lead_log(lead, reason="price_intent")
            reply = (
                "Claro ✅ Para cotizar correctamente necesito 3 datos:\n"
                "• Modelo exacto (o qué estás buscando)\n"
                "• Cantidad de usuarios/extensiones (o capacidad)\n"
                "• Ciudad (para instalación/envío)\n\n"
                "Si deseas, también puedes dejar tu email y te envío la proforma.\n\n"
                f"{contact_pack()}"
            )
            await send_whatsapp_text(from_number, reply)
            return {"status": "ok"}

        # Respuesta normal con OpenAI
        reply = await ask_openai(text_in, lead)
        await send_whatsapp_text(from_number, reply)

    except Exception as e:
        print("❌ Error:", str(e))

    return {"status": "ok"}


