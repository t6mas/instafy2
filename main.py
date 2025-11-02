from flask import Flask, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import requests, os, json, hashlib, time, sys
from datetime import datetime, timezone

# ===================== CONFIG ===================== #
USER = os.getenv("IG_USER", "typemkeell")               # cuenta pública a monitorear
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK")              # webhook de Discord (ENV en Render)
API_URL = "https://instagram120.p.rapidapi.com/api/instagram/stories"
API_KEY = os.getenv("X_RAPIDAPI_KEY")                   # clave RapidAPI (ENV en Render)

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "1200"))      # 20 min por defecto (segundos)
NOTIFY_NO_STORIES = os.getenv("NOTIFY_NO_STORIES", "1") == "1" # 1=notificar "sin historias"

# Notificar también "sin cambios" (misma historia), con cooldown para evitar spam
NOTIFY_NO_CHANGE = os.getenv("NOTIFY_NO_CHANGE", "1") == "1"
NO_CHANGE_COOLDOWN = int(os.getenv("NO_CHANGE_COOLDOWN", "1200"))  # 1 hora por defecto

# Keepalive interno (para evitar 502/hibernación sin monitor externo)
SELF_URL = os.getenv("SELF_URL")                        # ej: https://TUAPP.onrender.com/ping
KEEPALIVE_EVERY = int(os.getenv("KEEPALIVE_EVERY", "600"))  # cada 10 min por defecto
WATCHDOG_MAX_FAILS = int(os.getenv("WATCHDOG_MAX_FAILS", "3"))  # reinicia tras 3 fallos seguidos

PORT = int(os.getenv("PORT", "10000"))
STATE_PATH = "/tmp/insta_state.json"                    # persiste último id y timestamps

# Estado en memoria
state = {
    "last_id": None,
    "last_run_at": None,
    "last_status": "init",
    "checks": 0,
    "last_no_stories_ts": 0,
    "last_no_change_ts": 0
}

# Flag para no arrancar scheduler dos veces (python vs gunicorn)
_SCHEDULER_STARTED = False
_keepalive_failures = 0

# ===================== UTILIDADES ===================== #
def now_iso():
    return datetime.now(timezone.utc).isoformat()

def now_ts():
    return int(time.time())

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

def throttle(last_ts: int, cooldown: int) -> bool:
    """True si todavía estamos en cooldown (no notificar)."""
    return (now_ts() - int(last_ts or 0)) < cooldown

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

def send_discord(text: str, embed_url: str = "", mention_everyone: bool = False):
    if not WEBHOOK_URL:
        print("⚠️ DISCORD_WEBHOOK no configurado", flush=True)
        return
    payload = {"content": text}
    if mention_everyone:
        # Forzar ping a @everyone
        payload["content"] = f"@everyone {text}"
        payload["allowed_mentions"] = {"parse": ["everyone"]}
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
        r = requests.post(API_URL, headers=headers, json=body, timeout=25)
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
        if NOTIFY_NO_STORIES and not throttle(state.get("last_no_stories_ts", 0), NO_CHANGE_COOLDOWN):
            send_discord(f"🚫 No hay historias de @{USER} por ahora. ({state['last_run_at']})")
            state["last_no_stories_ts"] = now_ts(); save_state()
        return

    newest = items[0]
    nid = extract_id(newest)
    media_url = extract_media_url(newest)
    print(f"🆔 newest_id = {nid}", flush=True)

    if state.get("last_id") != nid:
        # NUEVA historia
        state["last_id"] = nid
        state["last_status"] = "notified"
        save_state()
        text = f"📸 Nueva historia de @{USER}! ({state['last_run_at']})"
        # 👉 ping a @everyone cuando es nueva
        send_discord(text, embed_url=media_url or f"https://www.instagram.com/stories/{USER}/", mention_everyone=True)
    else:
        # MISMA historia (sin cambios)
        print("⏭️ Sin cambios (misma historia).", flush=True)
        state["last_status"] = "no_change"; save_state()
        if NOTIFY_NO_CHANGE and not throttle(state.get("last_no_change_ts", 0), NO_CHANGE_COOLDOWN):
            send_discord(f"ℹ️ Sin cambios: @{USER} mantiene la misma historia. ({state['last_run_at']})")
            state["last_no_change_ts"] = now_ts(); save_state()

# ===================== FLASK + KEEPALIVE + SCHEDULER ===================== #
app = Flask(__name__)

@app.route("/")
def home():
    return "<h3>📡 Bot activo. /status estado, /check forzar chequeo, /ping keepalive.</h3>"

@app.route("/status")
def status():
    return jsonify({"user": USER, **state})

@app.route("/check")
def manual_check():
    check_and_notify()
    return jsonify({"user": USER, **state})

@app.route("/ping")
def ping():
    # endpoint ultra liviano para monitores o keepalive interno
    return "", 204

def self_keepalive():
    """Hace GET a /ping de tu propia app para mantenerla 'caliente'.
       Si falla varias veces seguidas, fuerza reinicio (watchdog)."""
    global _keepalive_failures
    if not SELF_URL:
        return
    try:
        resp = requests.get(SELF_URL + f"?t={int(time.time())}", timeout=10)
        ok = (200 <= resp.status_code < 400)
        print(f"🔁 self-keepalive status={resp.status_code}", flush=True)
        if ok:
            _keepalive_failures = 0
        else:
            _keepalive_failures += 1
    except Exception as e:
        _keepalive_failures += 1
        print(f"❌ self-keepalive error: {e}", flush=True)

    if _keepalive_failures >= WATCHDOG_MAX_FAILS:
        # Avisa y sale: Render relanza el proceso automáticamente
        try:
            send_discord("🔴 Watchdog: reiniciando el bot automáticamente (keepalive falló varias veces).")
        except Exception:
            pass
        print("⚠️ Watchdog activado → saliendo del proceso para reinicio por Render.", flush=True)
        sys.stdout.flush()
        os._exit(1)

def start_scheduler():
    load_state()
    if WEBHOOK_URL:
        send_discord(f"🟢 Bot iniciado. Monitoreando @{USER}.")
    scheduler = BackgroundScheduler(daemon=True)
    from datetime import datetime as dt
    # Chequeo de historias: primera ejecución inmediata y luego cada CHECK_INTERVAL
    scheduler.add_job(check_and_notify, "interval", seconds=CHECK_INTERVAL, next_run_time=dt.now())
    # Keepalive interno: corre siempre que SELF_URL esté configurada
    if SELF_URL:
        scheduler.add_job(self_keepalive, "interval", seconds=KEEPALIVE_EVERY, next_run_time=dt.now())
        print(f"🔧 Keepalive activo → {SELF_URL} cada {KEEPALIVE_EVERY}s (watchdog={WATCHDOG_MAX_FAILS})", flush=True)
    else:
        print("ℹ️ Keepalive interno desactivado (definí SELF_URL para habilitarlo).", flush=True)
    scheduler.start()
    print(f"🚀 Scheduler iniciado: checks cada {CHECK_INTERVAL}s", flush=True)

def start_scheduler_once():
    global _SCHEDULER_STARTED
    if not _SCHEDULER_STARTED:
        try:
            start_scheduler()
            _SCHEDULER_STARTED = True
        except Exception as e:
            print(f"❌ Error iniciando scheduler: {e}", flush=True)

# Arranca el scheduler también al importar (útil con gunicorn).
start_scheduler_once()

if __name__ == "__main__":
    # Con 'python main.py' esto asegura una 2ª llamada segura (no duplica gracias al flag).
    start_scheduler_once()
    app.run(host="0.0.0.0", port=PORT)
