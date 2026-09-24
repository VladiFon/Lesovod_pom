# -*- coding: utf-8 -*-
"""
Точка входа backend-слоя "Цифровой помощник лесовода".

Это НОВЫЙ, параллельный слой — main.py и screens/ десктоп-приложения не
менялись и продолжают работать как раньше. Запуск (из папки /backend):

    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

Документация (автогенерация OpenAPI): http://localhost:8000/docs
"""
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import legacy_bridge  # noqa: F401 — обязателен до import secrets_store
import secrets_store
import config as legacy_config

from app.database import init_db
from app.routers import (
    ai_log,
    archive,
    attendance,
    auth as auth_router,
    bot as bot_router,
    calendar as calendar_router,
    dashboard,
    delyanki,
    documents,
    inspection,
    lesokultury,
    map as map_router,
    notes,
    notifications,
    raskhod,
    settings as settings_router,
    tabel,
    taxation,
    tasks,
    trelevka,
    uhody,
    work_plan,
)

app = FastAPI(
    title="Цифровой помощник лесовода — API",
    description="Backend-слой поверх существующей бизнес-логики "
                 "(delyanka.py, db.py, генераторы документов, парсеры, forest_map.py). "
                 "Автогенерируемая схема доступна на /docs и /openapi.json.",
    version="0.1.0",
)

# На время разработки фронтенда открыто для всех источников — сузьте
# allow_origins до реального домена фронтенда перед продакшн-деплоем.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()
    secrets_store.apply_saved_secrets_to_env()
    # Прогрев кэша слоёв Живой карты (см. forest_map.warm_layer_cache) —
    # в фоновом потоке, чтобы не задерживать старт сервера чтением/
    # упрощением 55 МБ map_vydela.geojson. Импорт forest_map — здесь, а
    # не в начале файла, чтобы отсутствие geopandas на сервере (для
    # backend'ов без Живой карты) не мешало остальному приложению
    # стартовать вообще.
    def _warm_map_cache():
        try:
            import forest_map
            forest_map.warm_layer_cache(legacy_config.DB_PATH)
        except Exception:  # noqa: BLE001 — прогрев необязателен
            pass

    threading.Thread(target=_warm_map_cache, daemon=True).start()


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.include_router(auth_router.router)
app.include_router(bot_router.router)
app.include_router(ai_log.router)
app.include_router(archive.router)
app.include_router(calendar_router.router)
app.include_router(dashboard.router)
app.include_router(delyanki.router)
app.include_router(taxation.router)
app.include_router(lesokultury.router)
app.include_router(raskhod.router)
app.include_router(inspection.router)
app.include_router(map_router.router)
app.include_router(documents.router)
app.include_router(settings_router.router)
app.include_router(tasks.router)
app.include_router(uhody.router)
app.include_router(work_plan.router)
app.include_router(tabel.router)
app.include_router(attendance.router)
app.include_router(notes.router)
app.include_router(notifications.router)
app.include_router(trelevka.router)
