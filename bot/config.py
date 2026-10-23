"""Carga y validación de la configuración (config.yaml con valores por defecto)."""
from __future__ import annotations

import copy
import logging
from pathlib import Path

import yaml

log = logging.getLogger("bot.config")

# Valores por defecto: el config.yaml puede sobrescribir cualquier clave.
DEFAULTS: dict = {
    "filtros": {
        "descuento_minimo": 55,     # % mínimo general
        # Umbral MÁS BAJO para tiendas prioritarias (más volumen ahí):
        "descuento_minimo_tiendas": {
            "falabella": 50,
            "ripley": 45,
            "tottus": 50,
            "plazavea": 55,
            "oechsle": 55,
            "carsa": 55,
        },
        "precio_minimo": 15,        # S/ - evita productos absurdos de S/1-2
        "precio_maximo": None,      # None = sin tope
        "palabras_clave": [],       # vacío = todas las categorías
        "excluir_palabras": [],     # p. ej. ["suscripción", "gift card"]
        # ---- Anti-repetición (por NADA del mundo se repiten ofertas) ----
        "evitar_repetir_productos": True,  # mismo producto (en cualquier tienda o
                                           # variante) ya avisado → no se vuelve a
                                           # enviar, salvo nuevo RÉCORD de precio bajo
        # ---- Anti-inflado (precios "antes" falsos) ----
        "razon_original_maxima": 12,       # ignora si "antes" > 12× el precio actual; 0 = off
        "precios_originales_repetidos": 4, # mismo "antes" en ≥4 productos = inflado; 0 = off
        "descartar_descuentos_permanentes": False,  # false = solo advierte (⚠️) pero envía
    },
    "tiendas": {
        "plazavea": {"activa": True, "max_paginas": 2},
        "falabella": {
            "activa": True,
            "max_paginas": 2,
            "urls": [
                # Collection general de descuentos CMR (60k+ productos)
                "https://www.falabella.com.pe/falabella-pe/collection/descuentos-cmr",
                # Filtras por categoría sobre la colección de descuentos:
                "https://www.falabella.com.pe/falabella-pe/collection/descuentos-cmr"
                "?f.product.L0_category_paths=CATG11950%7C%7CModa",  # ROPA
                "https://www.falabella.com.pe/falabella-pe/collection/descuentos-cmr"
                "?f.product.L0_category_paths=CATG36090%7C%7CCalzado%20y%20zapatillas",
                "https://www.falabella.com.pe/falabella-pe/collection/descuentos-cmr"
                "?f.product.L0_category_paths=CATG33544%7C%7CNi%C3%B1os%20y%20Jugueter%C3%ADa",  # JUGUETES
                "https://www.falabella.com.pe/falabella-pe/collection/descuentos-cmr"
                "?f.product.L0_category_paths=cat40793%7C%7CTecnolog%C3%ADa",  # TECH
                "https://www.falabella.com.pe/falabella-pe/collection/descuentos-cmr"
                "?f.product.L0_category_paths=CATG11947%7C%7CDecohogar",  # HOGAR
                "https://www.falabella.com.pe/falabella-pe/category/cat40712/Laptops",
            ],
        },
        "ripley": {
            "activa": True,
            "max_paginas": 2,
            "urls": [
                "https://simple.ripley.com.pe/tecnologia/computacion/laptops",
                "https://simple.ripley.com.pe/tecnologia/tv-y-cine-en-casa/televisores",
                "https://simple.ripley.com.pe/electrohogar/linea-blanca/ver-todo",
                "https://simple.ripley.com.pe/mujer/ropa-mujer/ver-todo",  # ROPA MUJER
                "https://simple.ripley.com.pe/hombre/ropa-hombre/ver-todo",  # ROPA HOMBRE
            ],
        },
        "oechsle": {"activa": True, "max_paginas": 2},
        "tottus": {
            "activa": True,
            "max_paginas": 2,
            "urls": [
                "https://www.tottus.com.pe/tottus-pe/lista/CATG47976/Televisores",
                "https://www.tottus.com.pe/tottus-pe/lista/CATG47996/Smartphones",
                "https://www.tottus.com.pe/tottus-pe/lista/CATG48293/Electrohogar",
                "https://www.tottus.com.pe/tottus-pe/lista/CATG16066/Abarrotes",  # ABARROTES
            ],
        },
        "carsa": {"activa": True, "max_paginas": 2},
    },
    "notificaciones": {
        "max_por_corrida": 40,      # tope de mensajes por ejecución (anti-spam)
        "pausa_entre_mensajes_seg": 1.5,
        "resumen": True,            # enviar mensaje resumen antes de las ofertas
        "prioridad_tiendas": ["falabella", "ripley"],  # se envían primero si tienen ofertas
    },
    "http": {
        "timeout_seg": 25,
        "reintentos": 3,
        "pausa_min_seg": 1.0,       # pausa aleatoria entre peticiones (scraping responsable)
        "pausa_max_seg": 2.5,
    },
    "estado": {
        "ruta": "data/estado.json",
        "historial_max_por_producto": 30,
        "historial_max_productos": 5000,
        # Tras N días SIN verse del todo, el registro de notificación se poda.
        # Con 365 una oferta NO se re-avisa nunca (solo si baja de precio).
        "dias_retencion_notificados": 365,
    },
}


def _fusionar(base: dict, sobre: dict) -> dict:
    """Fusión recursiva: los valores del YAML sobrescriben los defaults."""
    resultado = copy.deepcopy(base)
    for clave, valor in (sobre or {}).items():
        if isinstance(valor, dict) and isinstance(resultado.get(clave), dict):
            resultado[clave] = _fusionar(resultado[clave], valor)
        else:
            resultado[clave] = valor
    return resultado


def cargar_config(ruta: str = "config.yaml") -> dict:
    """Carga config.yaml (opcional) fusionado sobre los valores por defecto."""
    cfg = copy.deepcopy(DEFAULTS)
    archivo = Path(ruta)
    if archivo.exists():
        datos = yaml.safe_load(archivo.read_text(encoding="utf-8")) or {}
        if not isinstance(datos, dict):
            raise ValueError(f"{ruta} debe contener un diccionario YAML")
        cfg = _fusionar(cfg, datos)
        log.info("Configuración cargada desde %s", ruta)
    else:
        log.warning("No existe %s; se usan valores por defecto", ruta)

    # Validaciones mínimas con mensajes claros
    f = cfg["filtros"]
    if not (0 < float(f["descuento_minimo"]) <= 100):
        raise ValueError("filtros.descuento_minimo debe estar entre 1 y 100")
    if float(f["precio_minimo"]) < 0:
        raise ValueError("filtros.precio_minimo no puede ser negativo")

    # Solo tiendas registradas y con config
    from .stores import REGISTRO  # importación tardía para evitar ciclos

    desconocidas = [t for t in cfg["tiendas"] if t not in REGISTRO]
    if desconocidas:
        log.warning("Tiendas en config sin módulo (se ignoran): %s", ", ".join(desconocidas))
    cfg["tiendas"] = {k: v for k, v in cfg["tiendas"].items() if k in REGISTRO}
    return cfg
