# 🔎 Bot de Ofertas Perú (Telegram)

Bot **100% gratuito** que revisa tiendas peruanas y te avisa por Telegram de
los productos con **70% o más de descuento** (con nivel 🟢 70%+, 🟠 80%+,
🔴 90%+). Sin Apify, sin servicios de scraping de pago: solo Python + APIs
públicas/JSON embebido + GitHub Actions.

## Tiendas soportadas (y cómo se obtienen los datos)

| Tienda | Método (probado en vivo) | Notas |
|---|---|---|
| **Plaza Vea** | API VTEX pública `/api/catalog_system/pub/products/search` ✅ | Ordena por mayor descuento con `O=OrderByBestDiscountDESC` |
| **Falabella Perú** | JSON `__NEXT_DATA__` del HTML (SSR) ✅ | Listados paginados con `?page=N`; precios en `prices[]` |
| **Ripley Perú** | JSON `__NEXT_DATA__` → `findabilityProps.data.products` ✅ | `ripley.com.pe` redirige a `simple.ripley.com.pe` |
| **Oechsle** | API VTEX pública ✅ | Igual que Plaza Vea |
| **Tottus** | JSON `__NEXT_DATA__` (¡mismo motor que Falabella!) ✅ | Rutas `/tottus-pe/lista/CATG...` |
| **Carsa** | API VTEX pública ✅ | Pese a verse "clásica", Carsa **es VTEX** |

> 🔎 **Importante**: el descuento se calcula SIEMPRE con
> `(precio_original − precio_actual) / precio_original × 100`.
> El % que muestra la tienda se ignora.

## Características

- **Anti-spam**: máximo 15 mensajes por corrida, ordenados por mayor descuento.
- **Sin duplicados**: guarda en `data/estado.json` lo ya notificado; solo
  vuelve a avisar si el precio **bajó**.
- **Detección de falsos descuentos**: historial de precios por producto; si el
  "precio original" no coincide con lo que se ha visto, el mensaje incluye ⚠️.
- **Robusto**: si una tienda falla, las demás siguen. Reintentos con backoff,
  timeouts, User-Agent realista y pausas aleatorias entre peticiones.
- **Gratis**: corre en GitHub Actions (plan gratuito: 2,000 min/mes; este bot
  usa ~720 min/mes con cron horario).

---

## 1️⃣ Crear el bot en Telegram (BotFather)

1. Abre Telegram y busca **@BotFather** (verificado con ✔).
2. Escribe `/newbot`.
3. Elige un nombre (ej: `Ofertas Perú Bot`) y un usuario único
   (ej: `ofertas_peru_mi_bot`). Si el usuario ya existe, BotFather te avisa.
4. BotFather te entrega un **token** tipo `123456789:AAH...xyz`.
   ⚠️ Guárdalo como secreto: quien lo tiene puede enviar mensajes como tu bot.

## 2️⃣ Obtener tu chat_id

1. Abre tu bot en Telegram (busca su usuario) y presiona **Start** o escribe
   `/hola` (cualquier mensaje sirve).
2. En tu navegador, abre (reemplaza el token):

   ```
   https://api.telegram.org/bot<TU_TOKEN>/getUpdates
   ```

3. Busca `"chat":{"id": 555555555 ...}` → ese número es tu **chat_id**.
   (Si usas grupos, el id es negativo, ej. `-1001234567890`.)

## 3️⃣ Probar en local (opcional pero recomendado)

Necesitas [Python 3.11+](https://www.python.org/downloads/) instalado.

```bat
cd bot-telegram-ofertas
python -m venv .venv
.venv\Scripts\activate         (en Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt

:: Prueba sin enviar nada a Telegram:
python -m bot --dry-run
```

Con `--dry-run` verás algo como:

```
🔎 MODO DE PRUEBA (--dry-run): no se envió nada a Telegram
  ✓ plazavea   vistos=100  nuevas=2  descartados=98 (3.1s)
  ✓ falabella  vistos=96   nuevas=5  descartados=91 (5.4s)
...
  1. 🔴 [90%+] 93.2%  CARSA      Audífonos Sony MDR-EX15...
     antes S/5,619.00 → ahora S/29.00  id=12345 https://www.carsa.pe/...
```

Para la corrida real (envía a Telegram):

```bat
set TELEGRAM_BOT_TOKEN=123456:AA...
set TELEGRAM_CHAT_ID=555555555
python -m bot
```

## 4️⃣ Subir el proyecto a GitHub

1. Crea una cuenta en [github.com](https://github.com) (gratis).
2. Botón **+ → New repository** → nombre `bot-telegram-ofertas`, **Private**
   (recomendado) → Create repository.
3. Sube los archivos. Opción fácil (web): en la página del repo vacío,
   **uploading an existing file** y arrastra TODO el contenido de esta carpeta
   (sin la carpeta `.venv`).

   Opción git (desde esta carpeta):

   ```bat
   git init
   git add .
   git commit -m "Bot de ofertas Perú"
   git branch -M main
   git remote add origin https://github.com/TU-USUARIO/bot-telegram-ofertas.git
   git push -u origin main
   ```

## 5️⃣ Configurar los Secrets

En tu repo de GitHub: **Settings → Secrets and variables → Actions → New repository secret** y crea dos:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | el token de BotFather |
| `TELEGRAM_CHAT_ID` | tu chat_id |

## 6️⃣ Activar el cron y ejecutar

- El archivo `.github/workflows/ofertas.yml` ya trae:
  - **cron cada hora** a los :17 UTC (12:17 p. m. y 6:17 p. m. en Perú).
  - **Ejecución manual**: pestaña **Actions → 🔎 Ofertas Perú → Run workflow**.
- La primera vez que subas el workflow, GitHub puede pedirte habilitarlo:
  pestaña **Actions → I understand my workflows, go ahead and enable them**.
- El estado (`data/estado.json`) se guarda automáticamente con `git commit`
  tras cada corrida.

---

## Persistencia del estado: ¿JSON en el repo o caché de Actions?

Este proyecto usa **commit del JSON al repositorio**, y esta es la razón:

| Opción | Ventajas | Límites |
|---|---|---|
| **Commit de `data/estado.json`** ✅ | 100% confiable y auditable; funciona siempre; puedes ver el historial | El repo crece un poco (~pocos KB por corrida, acotado por los topes de poda); si dos corridas corren a la vez podría haber conflicto (lo evitamos con `concurrency`) |
| Caché de Actions | Rápida | **Best-effort**: GitHub puede no restaurarla (evicción tras ~7 días sin uso, límite de 10 GB compartido); las cachés son inmutables (necesitas claves únicas cada corrida, que acumulan basura); **no la uses como base de datos** |

## Personalización rápida (config.yaml)

```yaml
filtros:
  descuento_minimo: 70     # sube a 80 si quieres solo descuentos bestiales
  precio_minimo: 15        # sube a 30/50 para ignorar accesorios baratos
  palabras_clave: []       # p. ej. ["laptop", "celular", "televisor"]
  excluir_palabras: []     # p. ej. ["gift card"]
tiendas:
  falabella:
    activa: true
    max_paginas: 2         # más páginas = más cobertura, más peticiones
    urls: [...]            # agrega tus categorías favoritas
notificaciones:
  max_por_corrida: 15      # baja a 5 si recibes muchos mensajes
```

## Estructura del proyecto

```
├── .github/workflows/ofertas.yml   # cron horario + manual + guardado de estado
├── bot/
│   ├── main.py                     # orquestador + CLI (--dry-run, --tiendas…)
│   ├── config.py                   # carga config.yaml con defaults
│   ├── models.py                   # Producto (interfaz común)
│   ├── http_client.py              # UA, pausas aleatorias, reintentos, timeouts
│   ├── filters.py                  # cálculo real de descuento + filtros
│   ├── state.py                    # notificados + historial (JSON atómico)
│   ├── notifier.py                 # Bot API: foto + caption + botón
│   └── stores/
│       ├── base.py                 # interfaz común de tiendas
│       ├── vtex.py                 # parser VTEX compartido
│       ├── plazavea.py  oechsle.py  carsa.py
│       ├── falabella.py            # parser plataforma Falabella (SSR)
│       ├── falabella_pe.py  tottus.py
│       └── ripley.py
├── data/estado.json                # se commitea en cada corrida
├── config.yaml                     # tu configuración
├── requirements.txt
└── README.md
```

## Preguntas frecuentes

**¿Cada cuánto revisa?** Cada hora (cron). GitHub puede retrasar unos minutos
los crons en horas pico; es normal.

**No me llegan mensajes.** Verifica: (1) el bot tiene el token correcto,
(2) le escribiste `/start` a tu bot, (3) el `chat_id` está bien, (4) la Action
fue verde y en logs no aparece `Telegram 400`.

**Aparece "⚠️ posible precio inflado".** Es el sistema anti-fraude: el
"precio original" de la tienda no coincide con lo que se ha visto antes del
producto. El bot te avisa igual, pero con la advertencia.

**¿Es legal/ético?** El bot solo lee páginas públicas con pocas peticiones
por hora (≤ ~10 por tienda), con pausas y User-Agent legítimo. Es uso
personal y moderado.

**¿Cuánto gasto en GitHub?** Nada: el plan gratuito da 2,000 min/mes de
Actions y este job usa ~1 minuto por hora (~720 min/mes).
