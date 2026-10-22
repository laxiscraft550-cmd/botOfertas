#!/usr/bin/env python3
"""Ayudante para obtener tu chat_id de Telegram sin copiar JSON a mano.

Uso:
    python obtener_chat_id.py

1. Te pide el token de BotFather (el que empieza con números y dos puntos).
2. Antes de ejecutarlo, asegúrate de haberle escrito CUALQUIER mensaje a tu
   bot en Telegram (ej. /start).
3. Imprime tu chat_id listo para copiar al Secret TELEGRAM_CHAT_ID.
"""
from __future__ import annotations

import sys

import requests


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    token = input("Pega tu token de BotFather (se ve como 123456:AA...) y presiona Enter:\n> ").strip()
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

    actualizaciones = datos.get("result") or []
    if not actualizaciones:
        print(
            "No hay mensajes registrados para este bot todavía.\n"
            "Abre tu bot en Telegram, presiona START (o escribe /hola) "
            "y vuelve a ejecutar este script."
        )
        return 1

    # Tomar el chat del último mensaje recibido
    chat = actualizaciones[-1].get("message", {}).get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id:
        print("No se encontró un chat en los mensajes. Revisa que escribiste al bot correcto.")
        return 1

    nombre = chat.get("first_name") or chat.get("title") or ""
    tipo = chat.get("type") or "desconocido"
    print("\n" + "=" * 50)
    print(f"✅ ¡Listo! chat_id de {nombre} ({tipo}):")
    print(f"\n   {chat_id}\n")
    print("Cópialo como Secret TELEGRAM_CHAT_ID en GitHub.")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
