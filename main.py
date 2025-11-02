from flask import Flask, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import requests, os, json, hashlib
from datetime import datetime, timezone

# ===================== CONFIG ===================== #
USER = os.getenv("IG_USER", "typemkeell")               # cuenta pública a monitorear
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK")              # webhook de Discord (ENV en Render)
API_URL = "https://instagram120.p.rapidapi.com/api/instagram/stories"
API_KEY = os.getenv("X_RAPIDAPI_KEY")                   # clave RapidAPI (ENV en Render)
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "1200"))  # 20 min por defecto (en segundos)
NOTIFY_NO_STORIES = os.getenv("NOTIFY_NO_STORIES", "1") == "1"  # 1=notificar "sin historias"
PORT = int(os.getenv("PORT", "10000"))

STATE_PATH = "/tmp/insta_state.json"                    # persiste último id (evita duplicados)

# Estado en memoria
state = {"last_id": None, "last_run_at": None, "last_status": "init", "checks": 0}

# ===================== UTILIDADES ===================== #
def now_iso():
    return datetime.now(timezone.utc).isoformat()

def load_state():
    try:
        with open(STATE_PATH, "r") as f:
            data = json.load(f)
            state.update(data)
    except Exception:
        pass

def save_state():
    try:
        with open(STATE_PATH, "w") as f:
            json.dump(state, f)
    except Exception:
        pass

def extract_items(payload: dict):
    """Tolera distintas formas de respuesta de la API."""
    if isinstance(payload, dict):
        if isinstance(payload.get("result"), list):
            return payload["result"]
        if isinstance(payload.get("data"), dict) and isinstance(payload["data"].get("items"), list):
            return payload["data"]["items"]
        if isinstance(payload.get("data"), list):
            return payload["data"]
    if isinstance(payload, list):
        return payload
    return []

def extract_id(item: dict) -> str:
    for k in ("id", "pk", "media_pk", "mediaId"):
        if k in item:
            return str(item[k])
    # Fallback estable
    return hashlib.md5(json.dumps(item, sort_keys=True).encode()).hexdigest()

def extract_media_url(item: dict) -> str:
    # Campos directos usuales
    for k in ("media", "url", "video_url", "image_url", "display_url"):
        if item.get(k):
            return item[k]
    # Anidados
    if item.get("video_versions"):
        u = item["video_versions"][0].get("url")
        if u: return u
    if item.get("image_versions2") and item["image_versions2"].get("candidates"):
        u = item["image_versions2"]["candidates"][0].get("url")
        if u: return u
    return ""

def send_discord(text: str, embed_url: str = ""):
    if not WEBHOOK_URL:
        print("⚠️ DISCORD_WEBHOOK no configurado", flush=True)
        return
    payload = {"content": text}
    if embed_url:
        payload["embeds"] = [{
            "title": f"Historia de @{USER}",
            "url": f"https://www.instagram.com/stories/{USER}/",
            "image": {"url": embed_url}
        }]
    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=15)
        print(f"↩️ Discord {r.status_code}", flush=True)
    except Exception as e:
        print(f"❌ Error enviando a Discord: {e}", flush=True)

# ===================== CHEQUEO PRINCIPAL ===================== #
def check_and_notify():
    state["checks"] += 1
    state["last_run_at"] = now_iso()
    print(f"\n⏱️ Check #{state['checks']} @ {state['last_run_at']}", flush=True)

    if not API_KEY:
        print("❌ Falta X_RAPIDAPI_KEY en variables de entorno.", flush=True)
        state["last_status"] = "no_api_key"; save_state(); return

    headers = {
        "content-type": "application/json",
        "X-RapidAPI-Key": API_KEY,
        "X-RapidAPI-Host": "instagram120.p.rapidapi.com"
    }
    body = {"username": USER}

    try:
        r = requests.post(API_URL, headers=headers, json=body, timeout=20)
        print(f"📡 API {r.status_code}", flush=True)
        preview = (r.text[:300] + "…") if len(r.text) > 300 else r.text
        print(f"🧾 Respuesta (preview): {preview}", flush=True)
        if not r.ok:
            state["last_status"] = f"api_error_{r.status_code}"; save_state(); return
        payload = r.json()
    except Exception as e:
        print(f"❌ Error HTTP/JSON: {e}", flush=True)
        state["last_status"] = "http_json_error"; save_state(); return

    items = extract_items(payload)
    if not items:
        print("🔍 No hay historias.", flush=True)
        state["last_status"] = "no_stories"; save_state()
        if NOTIFY_NO_STORIES:
            send_discord(f"🚫 No hay historias de @{USER} por ahora. ({state['last_run_at']})")
        return

    newest = items[0]
    nid = extract_id(newest)
    media_url = extract_media_url(newest)
    print(f"🆔 newest_id = {nid}", flush=True)

    if state.get("last_id") != nid:
        state["last_id"] = nid
        state["last_status"] = "notified"
        save_state()
        text = f"📸 Nueva historia de @{USER}! ({state['last_run_at']})"
        send_discord(text, embed_url=media_url or f"https://www.instagram.com/stories/{USER}/")
    else:
        print("⏭️ Sin cambios (misma historia).", flush=True)
        state["last_status"] = "no_change"; save_state()

# ===================== FLASK + SCHEDULER ===================== #
app = Flask(__name__)

@app.route("/")
def home():
    return "<h3>📡 Bot activo. Ver /status para estado y /check para forzar chequeo.</h3>"

@app.route("/status")
def status():
    return jsonify({"user": USER, **state})

@app.route("/check")
def manual_check():
    check_and_notify()
    return jsonify({"user": USER, **state})

def start_scheduler():
    load_state()
    if WEBHOOK_URL:
        send_discord(f"🟢 Bot iniciado. Monitoreando @{USER}.")
    scheduler = BackgroundScheduler(daemon=True)
    from datetime import datetime as dt
    # Primera ejecución inmediata y luego cada CHECK_INTERVAL
    scheduler.add_job(check_and_notify, "interval", seconds=CHECK_INTERVAL,
                      next_run_time=dt.now())
    scheduler.start()
    print(f"🚀 Scheduler iniciado cada {CHECK_INTERVAL}s", flush=True)

if __name__ == "__main__":
    print("🟢 Cargando servicio…", flush=True)
    try:
        start_scheduler()
    except Exception as e:
        print(f"❌ Error iniciando scheduler: {e}", flush=True)
    app.run(host="0.0.0.0", port=PORT)
