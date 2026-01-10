import os
import re
import time
import json
import math
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
OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

# -------------------------
# ENV - Click to Call
# -------------------------
CLICK_TO_CALL = os.getenv("CLICK_TO_CALL", "")

# -------------------------
# ENV - Webs
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

# -------------------------
# RAG store (knowledge_store.json)
# -------------------------
STORE_PATH = "knowledge_store.json"
STORE_DOCS = []
STORE_EMBEDS = []

def _dot(a, b):
    return sum(x*y for x, y in zip(a, b))

def _norm(a):
    return math.sqrt(sum(x*x for x in a))

def _cosine(a, b):
    na = _norm(a)
    nb = _norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return _dot(a, b) / (na * nb)

def load_store():
    global STORE_DOCS, STORE_EMBEDS
    try:
        if not os.path.exists(STORE_PATH):
            print("📦 RAG store not found:", STORE_PATH)
            return
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        docs = data.get("docs", [])
        STORE_DOCS = docs
        STORE_EMBEDS = [d.get("embedding", []) for d in docs]
        print(f"📦 RAG store loaded: {len(STORE_DOCS)} chunks | size={os.path.getsize(STORE_PATH)} bytes")
    except Exception as e:
        print("❌ Error loading RAG store:", str(e))

load_store()

async def embed_query(text: str):
    if not OPENAI_API_KEY:
        return []
    url = "https://api.openai.com/v1/embeddings"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": OPENAI_EMBED_MODEL, "input": text}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=headers, json=payload)
    if r.status_code != 200:
        print("❌ Embedding error:", r.status_code, r.text)
        return []
    return (r.json()["data"][0]["embedding"] or [])

def rag_search(query_embedding, top_k=6):
    if not STORE_DOCS or not query_embedding:
        return []
    scored = []
    for i, emb in enumerate(STORE_EMBEDS):
        if not emb:
            continue
        score = _cosine(query_embedding, emb)
        scored.append((score, i))
    scored.sort(reverse=True, key=lambda x: x[0])
    out = []
    for score, idx in scored[:top_k]:
        doc = STORE_DOCS[idx]
        out.append({
            "score": score,
            "source": doc.get("source", ""),
            "text": doc.get("text", "")
        })
    return out

def build_rag_context(results):
    if not results:
        return ""
    # armamos contexto breve y útil
    lines = ["CONTEXTO TÉCNICO (no inventar; usar esto como fuente):"]
    for r in results:
        src = r.get("source", "")
        txt = (r.get("text", "") or "").strip()
        if not txt:
            continue
        lines.append(f"- Fuente: {src}\n{txt}")
    return "\n\n".join(lines)[:12000]  # límite razonable

# -------------------------
# Yeastar determinístico (ANTI-ALUCINACIÓN)
# -------------------------
YEASTAR_APPLIANCE_CAPACITY = {
    "P520": {"usuarios": "20", "llamadas": "10"},
    "P550": {"usuarios": "50", "llamadas": "25"},
    "P560": {"usuarios": "100 (base) o 200 (licencia)", "llamadas": "30 o 60"},
    "P570": {"usuarios": "300 / 400 / 500", "llamadas": "60 / 90 / 120"},
}

YEASTAR_S_CAPACITY = {
    "S412": {"usuarios": "20", "llamadas": "8"},
    "S20": {"usuarios": "20", "llamadas": "10"},
    "S50": {"usuarios": "50", "llamadas": "25"},
}

YEASTAR_MODELS = ["P520","P550","P560","P570","S412","S20","S50"]

def find_models(text: str):
    t = (text or "").upper()
    found = []
    for m in YEASTAR_MODELS:
        if m in t:
            found.append(m)
    # unique preserving order
    seen = set()
    out = []
    for m in found:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out

def is_capacity_question(text: str) -> bool:
    t = (text or "").lower()
    keywords = [
        "cuanto", "cuánt", "usuarios", "extensiones", "internos",
        "llamadas", "simult", "capacidad", "soporta"
    ]
    return any(k in t for k in keywords)

def capacity_line_for_model(model: str) -> str:
    if model in YEASTAR_APPLIANCE_CAPACITY:
        cap = YEASTAR_APPLIANCE_CAPACITY[model]
        return f"✅ {model} (Appliance físico): {cap['usuarios']} usuarios/extensiones | {cap['llamadas']} llamadas simultáneas"
    if model in YEASTAR_S_CAPACITY:
        cap = YEASTAR_S_CAPACITY[model]
        return f"✅ {model} (S-Series físico): {cap['usuarios']} usuarios | {cap['llamadas']} llamadas simultáneas"
    return f"✅ {model}: (dato no cargado)"

def build_capacity_reply_multi(models):
    lines = ["Según nuestro catálogo Yeastar (equipos físicos):"]
    for m in models:
        lines.append(capacity_line_for_model(m))
    lines.append("")
    lines.append("Si me dices cuántas extensiones y cuántas llamadas simultáneas necesitas, te recomiendo la mejor opción y te preparo cotización.")
    return "\n".join(lines)

# -------------------------
# Endpoints base
# -------------------------
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

# -------------------------
# WhatsApp sender
# -------------------------
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

# -------------------------
# Intent helpers
# -------------------------
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

# -------------------------
# OpenAI (con RAG)
# -------------------------
async def ask_openai(user_text: str, lead: dict) -> str:
    if not OPENAI_API_KEY:
        return "⚠️ OpenAI no está configurado (falta OPENAI_API_KEY)."

    # RAG retrieval
    rag_context = ""
    try:
        q_emb = await embed_query(user_text)
        results = rag_search(q_emb, top_k=6)
        rag_context = build_rag_context(results)
        if rag_context:
            print("🧠 RAG hits:", [(round(r["score"], 3), r["source"]) for r in results[:3]])
        else:
            print("🧠 RAG hits: none")
    except Exception as e:
        print("❌ RAG error:", str(e))

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}

    internal_context = (
        f"Contexto interno (no lo muestres): wa_id={lead.get('wa_id')}, "
        f"phone={lead.get('phone')}, email={lead.get('email')}, human_requested={lead.get('human_requested')}.\n"
        "Regla: si phone/email ya existen, NO los vuelvas a pedir; confirma y avanza.\n"
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": internal_context},
    ]
    if rag_context:
        messages.append({"role": "system", "content": rag_context})
    messages.append({"role": "user", "content": user_text})

    payload = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "temperature": 0.2,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, headers=headers, json=payload)

    if r.status_code != 200:
        print("❌ OpenAI error:", r.status_code, r.text)
        return "Tuve un problema al generar la respuesta. ¿Puedes intentar de nuevo?"

    data = r.json()
    out = (data["choices"][0]["message"]["content"] or "").strip()
    return out or "¿Me das un poco más de detalle?"

# -------------------------
# Webhook receiver
# -------------------------
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

        # Captura datos de lead
        phone, email = extract_phone_email(text_in)
        if phone and not lead.get("phone"):
            lead["phone"] = phone
        if email and not lead.get("email"):
            lead["email"] = email

        # --- FIX 1: Capacidades Yeastar (sin IA, multi-model) ---
        models = find_models(text_in)
        if models and is_capacity_question(text_in):
            reply = build_capacity_reply_multi(models)
            await send_whatsapp_text(from_number, reply)
            return {"status": "ok"}

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

        # Respuesta normal con OpenAI + RAG
        reply = await ask_openai(text_in, lead)
        await send_whatsapp_text(from_number, reply)

    except Exception as e:
        print("❌ Error:", str(e))

    return {"status": "ok"}


