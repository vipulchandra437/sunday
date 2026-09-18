from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.config.settings import config, settings


def _configure_logging() -> None:
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    logging.getLogger("sunday").info(
        "Sunday API starting with default model provider '%s'",
        config.default_model_provider,
    )
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Sunday Agent API", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()