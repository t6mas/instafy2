from flask import Flask
import threading, requests, time, os

# === CONFIGURACIÓN ===
USER = "typemkeell"
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK")
API_URL = "https://instagram120.p.rapidapi.com/api/instagram/stories"
API_KEY = os.getenv("X_RAPIDAPI_KEY")
CHECK_INTERVAL = 600  # 10 minutos

# === FLASK APP ===
app = Flask(__name__)

@app.route("/")
def home():
    return "<h2>📡 Bot activo y monitoreando historias de Instagram</h2>"

# === FUNCIÓN PRINCIPAL ===
def monitor():
    print(f"👀 Iniciando monitoreo de @{USER}...")
    if not API_KEY:
        print("⚠️ Falta X_RAPIDAPI_KEY en variables de entorno.")
    if not WEBHOOK_URL:
        print("⚠️ Falta DISCORD_WEBHOOK en variables de entorno.")

    # Mensaje inicial
    if WEBHOOK_URL:
        try:
            requests.post(WEBHOOK_URL, json={"content": f"🟢 Bot iniciado. Monitoreando @{USER}."})
        except Exception as e:
            print(f"❌ Error enviando mensaje inicial a Discord: {e}")

    last_id = None
    while True:
        try:
            headers = {
                "content-type": "application/json",
                "X-RapidAPI-Key": API_KEY,
                "X-RapidAPI-Host": "instagram120.p.rapidapi.com"
            }
            body = {"username": USER}
            r = requests.post(API_URL, headers=headers, json=body)

            print(f"📡 Llamada API: {r.status_code}")
            print("🧾 Respuesta parcial:", r.text[:200])  # Primeros 200 caracteres

            if r.ok:
                data = r.json().get("result", [])
                if data:
                    newest = data[0].get("id") or data[0].get("pk")
                    if newest != last_id:
                        last_id = newest
                        media = data[0].get("media") or ""
                        msg = f"📸 Nueva historia de @{USER}!\n{media}\nhttps://www.instagram.com/stories/{USER}/"
                        requests.post(WEBHOOK_URL, json={"content": msg})
                        print(msg)
                else:
                    print("🔍 No hay historias nuevas.")
            else:
                print(f"⚠️ Error API {r.status_code}: {r.text}")

        except Exception as e:
            print(f"❌ Error en el loop principal: {e}")

        time.sleep(CHECK_INTERVAL)

# === ARRANQUE ===
if __name__ == "__main__":
    print("🟢 Código cargado, intentando iniciar el hilo de monitor...")
    try:
        t = threading.Thread(target=monitor, daemon=True)
        t.start()
        print("✅ Hilo de monitor iniciado correctamente.")
    except Exception as e:
        print(f"❌ Error al iniciar el hilo: {e}")

    app.run(host="0.0.0.0", port=10000)
