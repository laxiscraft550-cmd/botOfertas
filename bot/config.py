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
        "descuento_minimo": 70,     # % mínimo de descuento calculado
        "precio_minimo": 15,        # S/ - evita productos absurdos de S/1-2
        "precio_maximo": None,      # None = sin tope
        "palabras_clave": [],       # vacío = todas las categorías
        "excluir_palabras": [],     # p. ej. ["suscripción", "gift card"]
        # ---- Anti-inflado (precios "antes" falsos) ----
        "razon_original_maxima": 10,       # ignora si "antes" > 10× el precio actual (~90%+); 0 = off
        "precios_originales_repetidos": 4, # mismo "antes" en ≥4 productos = inflado; 0 = off
        "descartar_descuentos_permanentes": True,  # descarta precios que nunca cambiaron
    },
    "tiendas": {
        "plazavea": {"activa": True, "max_paginas": 2},
        "falabella": {
            "activa": True,
            "max_paginas": 2,
            "urls": [
                # Collection general de descuentos (60k+ productos paginados)
                "https://www.falabella.com.pe/falabella-pe/collection/descuentos-cmr",
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
            ],
        },
        "carsa": {"activa": True, "max_paginas": 2},
    },
    "notificaciones": {
        "max_por_corrida": 15,      # tope de mensajes por ejecución (anti-spam)
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
        "dias_retencion_notificados": 90,
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
