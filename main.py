import os
import re
import time
import json
import math
import httpx
from typing import Optional, Tuple
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
# ENV - Zoho Flow (Webhook)
# -------------------------
ZOHO_FLOW_WEBHOOK_URL = os.getenv("ZOHO_FLOW_WEBHOOK_URL", "")

# -------------------------
# CONTACTO OFICIAL (REAL)
# -------------------------
NUXWAY_PHONE_MOBILE = "(+591) 617 86583"
NUXWAY_PHONE_LANDLINE = "(+591) 4 483862"
NUXWAY_EMAIL_SALES = "ventas@nuxway.net"

# -------------------------
# Helpers: regex y keywords
# -------------------------
PHONE_RE = re.compile(r"(\+?\d[\d\s\-()]{6,}\d)")
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

CALLBACK_KEYWORDS = [
    "llámame", "llamarme", "me llamen", "me puedes llamar", "me pueden llamar",
    "llámame después", "llámame luego", "más tarde", "mañana", "en la tarde", "en la noche",
    "quiero que me llamen", "dejar un contacto", "pueden llamarme", "me llaman"
]

# -------------------------
# Estado en memoria por wa_id
# -------------------------
LEADS = {}  # wa_id -> dict

# -------------------------
# Normalización Bolivia: teléfono a 8 dígitos (para Zoho Bigin)
# -------------------------
def digits_only(s: str) -> str:
    return re.sub(r"\D+", "", s or "")

def normalize_bolivia_phone_8(raw: str) -> Optional[str]:
    """
    Devuelve teléfono de 8 dígitos si se puede. Si no, None.
    Reglas:
    - limpia a solo dígitos
    - si empieza con 591 y tiene >= 11, usa últimos 8
    - si tiene más de 8, usa últimos 8
    - si no tiene 8, None
    """
    d = digits_only(raw)
    if not d:
        return None

    if d.startswith("591") and len(d) >= 11:
        d = d[-8:]

    if len(d) > 8:
        d = d[-8:]

    if len(d) != 8:
        return None

    return d

def phone_is_valid_8(phone8: Optional[str]) -> bool:
    return bool(phone8) and len(phone8) == 8 and phone8.isdigit()

def is_valid_email(email: Optional[str]) -> bool:
    if not email:
        return False
    return bool(re.fullmatch(EMAIL_RE, email.strip()))

def clean_full_name(s: str) -> str:
    t = (s or "").strip()
    # Quita muletillas comunes
    t = re.sub(r"(?i)\b(hola|buenas|buenos días|buenos dias|buen dia|soy|me llamo|mi nombre es)\b[:,]?\s*", "", t).strip()
    t = re.sub(r"\s{2,}", " ", t)
    return t

def split_first_last(full_name: str) -> Tuple[Optional[str], str]:
    t = clean_full_name(full_name)
    if not t:
        return None, "SinApellido"

    parts = [p for p in t.split(" ") if p]
    if len(parts) == 1:
        return parts[0], "SinApellido"

    last = parts[-1]
    first = " ".join(parts[:-1])
    return first, last

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
    lines = ["CONTEXTO TÉCNICO (no inventar; usar esto como fuente):"]
    for r in results:
        src = r.get("source", "")
        txt = (r.get("text", "") or "").strip()
        if not txt:
            continue
        lines.append(f"- Fuente: {src}\n{txt}")
    return "\n\n".join(lines)[:12000]

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
# Zoho Flow sender
# -------------------------
async def send_to_zoho_flow(lead: dict):
    """
    Envía el lead capturado a Zoho Flow (Webhook Trigger).
    En Zoho Flow mapea estos campos para crear/actualizar contacto en Bigin/Zoho CRM.
    """
    if not ZOHO_FLOW_WEBHOOK_URL:
        print("⚠️ ZOHO_FLOW_WEBHOOK_URL no configurado; no se envía a Zoho.")
        return

    payload = {
        # EXISTENTES (no rompen tu Flow actual)
        "source": "whatsapp-bot-render",
        "wa_id": lead.get("wa_id"),
        "name": lead.get("name"),
        "city": lead.get("city"),
        "phone": lead.get("phone"),
        "email": lead.get("email"),
        "human_requested": bool(lead.get("human_requested")),
        "last_intent": lead.get("last_intent"),
        "created_at": lead.get("created_at"),
        "ts": int(time.time()),

        # NUEVOS (inteligencia)
        "first_name": lead.get("first_name"),
        "last_name": lead.get("last_name"),
        "phone_8": lead.get("phone_8"),
        "phone_valid": bool(lead.get("phone_valid")),
        "email_valid": bool(lead.get("email_valid")),
        "callback_requested": bool(lead.get("callback_requested")),
        "notes": lead.get("notes"),
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(ZOHO_FLOW_WEBHOOK_URL, json=payload)
        print("🟦 Zoho Flow status:", r.status_code, r.text)
    except Exception as e:
        print("❌ Zoho Flow error:", str(e))

# -------------------------
# Intent helpers
# -------------------------
def wants_human(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in HUMAN_KEYWORDS)

def wants_callback(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in CALLBACK_KEYWORDS)

def is_price_intent(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in PRICE_KEYWORDS)

def wants_click_to_call(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in CLICK_LINK_KEYWORDS)

def extract_phone_email(text: str) -> Tuple[Optional[str], Optional[str]]:
    email = None
    m2 = EMAIL_RE.search(text or "")
    if m2:
        email = m2.group(1).strip()

    # Busca varios candidatos y toma el primero que normalice a 8 dígitos
    candidates = PHONE_RE.findall(text or "")
    phone8 = None
    for c in candidates:
        p8 = normalize_bolivia_phone_8(c)
        if p8:
            phone8 = p8
            break

    return phone8, email

# ✅ Mejorado: detección simple de nombre/ciudad desde texto libre
def extract_name_city(text: str) -> Tuple[Optional[str], Optional[str]]:
    t = (text or "").strip()
    city = None

    m = re.search(r"\bde\s+([A-Za-zÁÉÍÓÚÑáéíóúñ\s]{3,})", t, re.IGNORECASE)
    if m:
        city = m.group(1).strip()
        city = re.sub(r"\s{2,}", " ", city)
        city = city.split(",")[0].strip()

    name = None
    mname = re.search(r"(?i)\b(soy|me llamo|mi nombre es)\s+([A-Za-zÁÉÍÓÚÑáéíóúñ\s]{2,})", t)
    if mname:
        name = mname.group(2).strip()
        name = re.split(r"(?i)\bde\s+", name)[0].strip()
    elif city:
        parts = re.split(r"(?i)\bde\s+", t, maxsplit=1)
        if parts and parts[0].strip():
            name = parts[0].strip()

    name = clean_full_name(name or "")
    return (name or None), city

def get_lead(wa_id: str) -> dict:
    if wa_id not in LEADS:
        LEADS[wa_id] = {
            "wa_id": wa_id,
            "created_at": int(time.time()),
            "human_requested": False,
            "callback_requested": False,

            "phone": None,        # compat
            "phone_8": None,      # nuevo
            "phone_valid": False,

            "email": None,
            "email_valid": False,

            "name": None,         # full name (texto)
            "first_name": None,
            "last_name": "SinApellido",

            "city": None,
            "notes": None,

            "last_intent": None,

            # ✅ para evitar enviar duplicado a Zoho en el mismo runtime
            "zoho_sent": False,
        }
    return LEADS[wa_id]

def lead_log(lead: dict, reason: str = ""):
    print(
        "🟩 LEAD:",
        {
            "wa_id": lead.get("wa_id"),
            "phone": lead.get("phone"),
            "phone_8": lead.get("phone_8"),
            "phone_valid": lead.get("phone_valid"),
            "email": lead.get("email"),
            "email_valid": lead.get("email_valid"),
            "name": lead.get("name"),
            "first_name": lead.get("first_name"),
            "last_name": lead.get("last_name"),
            "city": lead.get("city"),
            "human_requested": lead.get("human_requested"),
            "callback_requested": lead.get("callback_requested"),
            "last_intent": lead.get("last_intent"),
            "zoho_sent": lead.get("zoho_sent"),
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
    if lead.get("phone_valid") or lead.get("email"):
        return (
            "Perfecto ✅ Ya tengo tus datos.\n\n"
            f"{contact_pack()}\n\n"
            "En breve un asesor se comunicará contigo. ¿En qué ciudad estás?"
        )

    return (
        "Perfecto ✅ Un asesor puede ayudarte.\n"
        "Por favor compárteme (puede ser en cualquier orden):\n"
        "• Nombre\n"
        "• Ciudad\n"
        "• Teléfono (8 dígitos) o email\n\n"
        f"{contact_pack()}"
    )

def should_send_to_zoho(lead: dict) -> bool:
    """
    Enviar a Zoho si:
    - tenemos nombre (porque dijiste que nombre es mínimo)
    Y además alguno de:
      - email
      - phone válido 8 dígitos
      - pidió humano
      - pidió callback
    Así evitamos fallos por teléfono inválido y evitamos ruido.
    """
    has_name = bool(lead.get("first_name") or lead.get("name"))
    has_contact = bool(lead.get("email")) or bool(lead.get("phone_valid"))
    requested = bool(lead.get("human_requested")) or bool(lead.get("callback_requested"))
    return has_name and (has_contact or requested)

# -------------------------
# OpenAI (con RAG)
# -------------------------
async def ask_openai(user_text: str, lead: dict) -> str:
    if not OPENAI_API_KEY:
        return "⚠️ OpenAI no está configurado (falta OPENAI_API_KEY)."

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
        f"phone_8={lead.get('phone_8')}, phone_valid={lead.get('phone_valid')}, "
        f"email={lead.get('email')}, human_requested={lead.get('human_requested')}, callback_requested={lead.get('callback_requested')}.\n"
        "Regla: si phone/email ya existen, NO los vuelvas a pedir; confirma y avanza.\n"
        "Regla: si el usuario pide humano/callback, prioriza capturar nombre y un medio de contacto.\n"
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

        # 0) Detecta humano/callback en cualquier momento
        if wants_callback(text_in):
            lead["callback_requested"] = True
            lead["last_intent"] = lead.get("last_intent") or "callback"
            lead["notes"] = (lead.get("notes") or "")
            lead["notes"] = (lead["notes"] + "\n" if lead["notes"] else "") + f"Callback: {text_in}".strip()

        if wants_human(text_in):
            lead["human_requested"] = True
            lead["last_intent"] = "human"

        # 1) Captura teléfono/email y normaliza
        phone8, email = extract_phone_email(text_in)

        if email and not lead.get("email"):
            lead["email"] = email
        lead["email_valid"] = is_valid_email(lead.get("email"))

        if phone8 and not lead.get("phone"):
            # mantenemos compat: lead["phone"] sigue existiendo
            lead["phone"] = phone8

        lead["phone_8"] = normalize_bolivia_phone_8(lead.get("phone") or "")
        lead["phone_valid"] = phone_is_valid_8(lead.get("phone_8"))

        # 2) Captura nombre/ciudad y separa first/last
        name, city = extract_name_city(text_in)
        if name and not lead.get("name"):
            lead["name"] = name
        if city and not lead.get("city"):
            lead["city"] = city

        # Asegura first_name/last_name si hay name
        if lead.get("name") and (not lead.get("first_name") or not lead.get("last_name")):
            fn, ln = split_first_last(lead["name"])
            lead["first_name"] = fn
            lead["last_name"] = ln or "SinApellido"

        # 3) Auto-enviar a Zoho si corresponde (sin romper Bigin)
        if should_send_to_zoho(lead) and not lead.get("zoho_sent"):
            lead["last_intent"] = lead.get("last_intent") or "lead"
            lead_log(lead, reason="auto_send_zoho")
            await send_to_zoho_flow(lead)
            lead["zoho_sent"] = True

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
            lead_log(lead, reason="user_requested_human")
            await send_whatsapp_text(from_number, build_handoff_message(lead))

            # Si pidió humano y aún no se envió, intenta enviar
            if should_send_to_zoho(lead) and not lead.get("zoho_sent"):
                lead_log(lead, reason="send_zoho_on_human_request")
                await send_to_zoho_flow(lead)
                lead["zoho_sent"] = True

            return {"status": "ok"}

        # Si ya está en modo humano y manda datos -> confirmar y paquete completo
        if lead.get("human_requested") and (phone8 or email or name):
            lead_log(lead, reason="lead_data_received_after_handoff")

            if should_send_to_zoho(lead) and not lead.get("zoho_sent"):
                await send_to_zoho_flow(lead)
                lead["zoho_sent"] = True

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

