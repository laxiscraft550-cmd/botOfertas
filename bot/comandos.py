"""Manejo de comandos entrantes del bot (sin servidor permanente).

El bot corre por poco tiempo en GitHub Actions, así que en cada corrida
consulta la cola de actualizaciones de Telegram (getUpdates), responde a
los comandos y las limpia (ack con offset) para no reprocessarlas.

Comandos soportados:
    /start  → mensaje de activación + ayuda
    /help   → ayuda
    /status → resumen de la última revisión de tiendas
"""
from __future__ import annotations

import logging

import requests

log = logging.getLogger("bot.comandos")

AYUDA = (
    "🤖 Bot de ofertas Perú — activo\n\n"
    "Reviso tiendas peruanas cada hora y te aviso cuando hay ofertas REALES "
    "con 70% o más de descuento (con precios verificados contra el historial).\n\n"
    "Comandos:\n"
    "  /start  → este mensaje\n"
    "  /help   → esta ayuda\n"
    "  /status → resumen de la última revisión\n\n"
    "Los avisos llegan automáticamente; no hace falta pedirlos."
)


def _status_texto(stats: dict | None) -> str:
    if not stats:
        return "ℹ️ Aún no hay una revisión en esta corrida. Espera a la próxima (cada hora)."
    lineas = ["📊 Última revisión:", ""]
    for nombre, dato in stats.items():
        if "error" in dato:
            lineas.append(f"  ✖ {nombre}: error ({dato['error'][:60]})")
        else:
            lineas.append(
                f"  ✓ {nombre}: {dato['vistos']} vistos → {dato['nuevas']} ofertas nuevas"
            )
    return "\n".join(lineas)


def procesar_comandos(token: str, stats: dict | None = None) -> int:
    """Procesa comandos pendientes. Devuelve cuántos respondió."""
    api = f"https://api.telegram.org/bot{token}"
    try:
        respuesta = requests.get(f"{api}/getUpdates", timeout=20)
        datos = respuesta.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("No se pudo consultar getUpdates: %s", exc)
        return 0

    if not datos.get("ok"):
        log.warning("getUpdates devolvió error: %s", datos.get("description"))
        return 0

    actualizaciones = datos.get("result") or []
    if not actualizaciones:
        return 0

    respondidos = 0
    ultimo_id = 0
    for actualizacion in actualizaciones:
        ultimo_id = max(ultimo_id, int(actualizacion.get("update_id") or 0))
        mensaje = actualizacion.get("message") or actualizacion.get("edited_message") or {}
        texto = (mensaje.get("text") or "").strip()
        chat = mensaje.get("chat") or {}
        chat_id = chat.get("id")
        if not texto.startswith("/") or not chat_id:
            continue  # mensajes normales: solo consumirlos (ack)

        comando = texto.split()[0].split("@")[0].lower()
        if comando in ("/start", "/help", "/ayuda"):
            respuesta_texto = AYUDA
        elif comando == "/status":
            respuesta_texto = _status_texto(stats)
        else:
            respuesta_texto = f"🤔 Comando no reconocido: {comando}\n\n{AYUDA}"

        try:
            requests.post(
                f"{api}/sendMessage",
                data={"chat_id": chat_id, "text": respuesta_texto},
                timeout=20,
            )
            respondidos += 1
        except requests.RequestException as exc:
            log.warning("No se pudo responder %s: %s", comando, exc)

    # Ack: marcar todo como procesado para no volver a leerlo
    if ultimo_id:
        try:
            requests.get(f"{api}/getUpdates", params={"offset": ultimo_id + 1}, timeout=20)
        except requests.RequestException:
            pass

    if respondidos:
        log.info("Comandos respondidos: %d", respondidos)
    return respondidos
