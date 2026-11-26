"""Aviso diario por Telegram: te manda al celular los partidos del día y cómo salieron tus apuestas.

Para activarlo (una vez):
1. En Telegram, hablá con @BotFather, mandá /newbot y seguí los pasos. Te da un TOKEN.
2. Escribile algo a tu bot nuevo. Después entrá a https://api.telegram.org/bot<TOKEN>/getUpdates
   y copiá el número "id" de tu chat.
3. Pegá los dos en .streamlit/secrets.toml:
     TELEGRAM_BOT_TOKEN = "..."
     TELEGRAM_CHAT_ID = "..."
4. Programá este archivo para que corra cada día (Programador de tareas de Windows), o corrélo a mano:
     .venv\\Scripts\\python.exe aviso.py
"""
from __future__ import annotations

import requests

import engine
import historial as H
import storage


def enviar(texto: str) -> bool:
    token, chat = storage.secreto("TELEGRAM_BOT_TOKEN"), storage.secreto("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "text": texto, "parse_mode": "HTML"}, timeout=20)
    return r.ok


def configurado() -> bool:
    return bool(storage.secreto("TELEGRAM_BOT_TOKEN") and storage.secreto("TELEGRAM_CHAT_ID"))


def armar_texto(cfg: dict | None = None) -> str:
    cfg = cfg or engine.load_config()
    hoy = engine.hoy(cfg).isoformat()
    r = engine.correr(hoy, cfg=cfg)
    lineas = [f"<b>⚽ Tickets Super Match — {hoy}</b>", ""]

    # resultados de apuestas resueltas hoy
    try:
        H.buscar_resultados(cfg)
    except Exception:
        pass
    hist = H.cargar()
    stats = H.estadisticas(hist)
    recientes = [t for t in hist if H.estado(t) != "pendiente"][:3]
    if recientes:
        lineas.append("<b>Tus apuestas recientes:</b>")
        for t in recientes:
            e = H.estado(t)
            icono = "✅" if e == "ganado" else "❌"
            cob = H.cobro(t) or 0
            lineas.append(f"{icono} {t['nombre']} ${t['monto']:,.0f}" + (f" → cobrás ${cob:,.0f}" if e == "ganado" else " → perdido"))
        lineas.append(f"Acumulado: ${stats['ganancia']:+,.0f}")
        lineas.append("")

    ok = [x for x in r.resumen if x["ok"]]
    lineas.append(f"<b>Hoy hay {len(ok)} partidos analizables</b> de tus ligas:")
    for x in ok[:8]:
        m = x["match"]
        lineas.append(f"• {m.hora} {engine.sm_name(m.home)} vs {engine.sm_name(m.away)}")
    lineas.append("")
    lineas.append("Abrí la app y pegá las cuotas para ver si hoy hay valor (💰 Real). Si no hay, mejor no apostar.")
    return "\n".join(lineas)


if __name__ == "__main__":
    if not configurado():
        print("Falta configurar TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en .streamlit/secrets.toml (ver arriba).")
    else:
        ok = enviar(armar_texto())
        print("Aviso enviado." if ok else "No se pudo enviar (revisá el token y el chat id).")
