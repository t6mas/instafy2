import requests, time, os

# Configuración
USER = "typemkeell"  # 👈 cuenta pública a monitorear
WEBHOOK_URL = "https://discord.com/api/webhooks/1434371712673124443/_l7xzlrLHxe3zx5Lg6BvcQgY57mCQbW-LPBpuy_n3WHx_6HnkpXDApZ88rFJcS_qX-PT"  # 👈 tu webhook de Discord
API_URL = "https://instagram120.p.rapidapi.com/api/instagram/stories"

# Clave de RapidAPI guardada en variables de entorno (Render → Environment)
API_KEY = os.getenv("X_RAPIDAPI_KEY")

last_id = None

def get_stories():
    headers = {
        "content-type": "application/json",
        "X-RapidAPI-Key": API_KEY,
        "X-RapidAPI-Host": "instagram120.p.rapidapi.com"
    }
    body = {"username": USER}
    r = requests.post(API_URL, headers=headers, json=body)
    if r.ok:
        data = r.json()
        return data.get("result", [])
    else:
        print(f"⚠️ Error {r.status_code}: {r.text}")
        return []

print(f"👀 Monitoreando historias de @{USER}...")

while True:
    stories = get_stories()
    if stories:
        newest = stories[0].get("id") or stories[0].get("pk")
        if newest != last_id:
            last_id = newest
            media_url = stories[0].get("media", stories[0].get("image_versions2", {}).get("candidates", [{}])[0].get("url", ""))
            msg = f"📸 Nueva historia de @{USER}!\n{media_url}\nhttps://www.instagram.com/stories/{USER}/"
            requests.post(WEBHOOK_URL, json={"content": msg})
            print(msg)
    else:
        print("🔍 No hay historias nuevas.")
    time.sleep(1800)  # cada 10 minutos
