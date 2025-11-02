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
            body = {"username": USER}
            r = requests.post(API_URL, headers=headers, json=body)
            print(f"📡 Llamada API: {r.status_code}")

            # Mostrar los primeros 300 caracteres de la respuesta para depurar
            print("🧾 Respuesta parcial:", r.text[:300])

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
