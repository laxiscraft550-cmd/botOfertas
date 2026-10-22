"""Registro de tiendas disponibles (orden = prioridad de revisión)."""
from __future__ import annotations

from .base import Tienda
from .carsa import Carsa
from .falabella_pe import FalabellaPe
from .oechsle import Oechsle
from .plazavea import PlazaVea
from .ripley import Ripley
from .tottus import Tottus

# Orden de prioridad pedido por el usuario
REGISTRO: dict[str, type[Tienda]] = {
    "plazavea": PlazaVea,
    "falabella": FalabellaPe,
    "ripley": Ripley,
    "oechsle": Oechsle,
    "tottus": Tottus,
    "carsa": Carsa,
}

__all__ = ["REGISTRO", "Tienda"]
