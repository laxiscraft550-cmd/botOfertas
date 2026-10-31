#!/usr/bin/env python3
"""Ayudante para obtener tus chat_id de Telegram (privados y GRUPOS).

Uso:
    python obtener_chat_id.py

1. Te pide el token de BotFather.
2. Antes de ejecutarlo, escribele CUALQUIER mensaje a tu bot:
   - En privado: /start
   - En un GRUPO: primero agrega el bot al grupo y escribe
     @NombreDeTuBot /start  (mencionalo, o desactiva el modo privacidad
     con /setprivacy → Disabled en BotFather para no necesitar mencionarlo).
3. Imprime TODOS tus chats con su id, y un JSON listo para el secret
   TELEGRAM_CHATS_POR_RANGO (un chat por rango de descuento).
"""
from __future__ import annotations

import json
import sys

import requests

RANGOS = ["40-50", "50-60", "60-70", "70-80", "80-90", "90+"]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    token = input(
        "Pega tu token de BotFather (se ve como 123456:AA...) y presiona Enter:\n> "
    ).strip()
    if not token or ":" not in token:
        print("Ese token no parece válido (formato esperado: 123456789:AA...).")
        return 1

    print("\nConsultando https://api.telegram.org ...")
    try:
        respuesta = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates", timeout=20
        )
        datos = respuesta.json()
    except requests.RequestException as exc:
        print(f"No se pudo conectar: {exc}")
        return 1

    if not datos.get("ok"):
        print(f"Telegram respondió un error: {datos.get('description', datos)}")
        print("Revisa el token o vuelve a BotFather con /token")
        return 1

    # Recoger TODOS los chats de TODAS las actualizaciones
    chats: dict[int, dict] = {}
    for actualizacion in datos.get("result") or []:
        for clave in ("message", "edited_message", "channel_post"):
            chat = (actualizacion.get(clave) or {}).get("chat")
            if chat and isinstance(chat.get("id"), int):
                chats[chat["id"]] = chat

    if not chats:
        print(
            "No hay mensajes registrados para este bot todavía.\n"
            "Escribile /start a tu bot (y /start en cada grupo donde agregues\n"
            "al bot, mencionandolo: @TuBot /start) y vuelve a ejecutar este script."
        )
        return 1

    print("\n" + "=" * 64)
    print("TUS CHATS EN TELEGRAM")
    print("=" * 64)
    print(f"{'CHAT_ID':<20} {'TIPO':<10} NOMBRE")
    for chat_id, chat in sorted(chats.items()):
        nombre = chat.get("title") or chat.get("first_name") or "(sin nombre)"
        print(f"{chat_id:<20} {chat.get('type', '?'):<10} {nombre[:30]}")

    privado = next(
        (cid for cid, c in chats.items() if c.get("type") == "private"), None
    )
    if privado:
        print(
            f"\n👉 Secret TELEGRAM_CHAT_ID (chat base/resumen): {privado}"
        )

    grupos = [
        (cid, c.get("title", ""))
        for cid, c in sorted(chats.items())
        if c.get("type") in ("group", "supergroup")
    ]
    if grupos:
        print("\n👉 Para separar ofertas POR RANGO de descuento:")
        print("   Crea un grupo por rango (ej. 'Ofertas 50-60'), agrega tu bot")
        print("   y escribe @TuBot /start dentro. Luego copia este JSON al")
        print("   secret TELEGRAM_CHATS_POR_RANGO completando los id:\n")
        plantilla = {r: "<id del grupo de este rango>" for r in RANGOS}
        print("   " + json.dumps(plantilla, ensure_ascii=False))
        print("\n   Grupos detectados:")
        for cid, titulo in grupos:
            print(f"     {cid}  ←  {titulo}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
