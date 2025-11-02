from flask import Flask
import threading, requests, time, os

USER = "typemkeell"
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK")
API_URL = "https://instagram120.p.rapidapi.com/api/instagram/stories"
API_KEY = os.getenv("X_RAPIDAPI_KEY")
CHECK_INTERVAL = 600  # 10 min

app = Flask(__name__)

@app.route("/")
def home():
    return "<h2>📡 Bot activo y monitoreando historias de Instagram</h2>"

def monitor():
    print(f"👀 Iniciando monitoreo de @{USER}...")
    if WEBHOOK_URL:
        try:
            requests.post(WEBHOOK_URL, json={"content": f"🟢 Bot iniciado. Monitoreando @{USER}."})
        except:
            pass

    last_id = None
    while True:
        try:
            headers = {
                "content-type": "application/json",
                "X-RapidAPI-Key": API_KEY,
                "X-RapidAPI-Host": "instagram120.p.rapidapi.com"
            }
            r = requests.post(API_URL, headers=headers, json={"username": USER})
            print("📡 Llamada API:", r.status_code)
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
            print("❌ Error en el loop:", e)

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    threading.Thread(target=monitor, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
