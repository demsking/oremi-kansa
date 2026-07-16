# Copyright 2026 Sébastien Demanou. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
import logging
from contextlib import asynccontextmanager
from contextlib import AsyncExitStack
from time import perf_counter

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.responses import JSONResponse

from ..api import docs
from ..api import health
from ..utils.logger import configure_logging
from .database import PodcastDatabase
from .package import APP_DESCRIPTION
from .package import APP_NAME
from .package import APP_VERSION
from .server import create_mcp_server
from .settings import Settings


logger = logging.getLogger(__name__)


def log_startup_settings(settings: Settings) -> None:
  """Log every configured application setting without exposing secrets."""
  for name in settings.__class__.model_fields:
    value = getattr(settings, name)
    logger.info("Setting %s: %s", name, value)


def create_app(settings: Settings) -> FastAPI:
  http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(
      connect=settings.http_connect_timeout,
      read=settings.http_read_timeout,
      write=settings.http_write_timeout,
      pool=settings.http_pool_timeout,
    ),
    follow_redirects=True,
  )

  database = PodcastDatabase(settings, http_client)
  mcp_server = create_mcp_server(settings, database, http_client)

  @asynccontextmanager
  async def lifespan(app: FastAPI):
    startup_started = perf_counter()
    ready = False

    configure_logging(settings.log_level, settings.log_file)

    logger.info(f"{APP_NAME} v{APP_VERSION}")
    log_startup_settings(settings)

    app.state.mcp = mcp_server
    app.state.settings = settings

    stack = AsyncExitStack()

    try:
      await database.start()
      await stack.enter_async_context(mcp_server.session_manager.run())

      ready = True
      startup_duration = (perf_counter() - startup_started) * 1000
      logger.info(
        "Oremi Kànsà ready: duration_ms=%.1f",
        startup_duration,
      )

      yield
    finally:
      shutdown_started = perf_counter()

      if ready:
        logger.info("Shutting down Oremi Kànsà")
      else:
        logger.warning("Oremi Kànsà startup aborted; cleaning up resources")

      try:
        await stack.aclose()
      finally:
        await database.close()
        await http_client.aclose()

      shutdown_duration = (perf_counter() - shutdown_started) * 1000

      logger.info("Oremi Kànsà stopped: duration_ms=%.1f", shutdown_duration)

  app = FastAPI(
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
    title="Oremi Kànsà",
    version=APP_VERSION,
    description=APP_DESCRIPTION,
    root_path=settings.api_prefix,
    servers=[
      {"url": settings.api_prefix},
    ],
    license_info={
      "name": "Apache 2.0",
      "url": "http://www.apache.org/licenses/LICENSE-2.0.html",
    },
    openapi_tags=[
      health.API_TAG_METADATA,
    ],
  )

  @app.exception_handler(Exception)
  async def unhandled_exception_handler(_, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled application error")
    return JSONResponse(
      status_code=500,
      content={"detail": "Internal server error", "error": str(exc)},
    )

  @app.get("/", include_in_schema=False)
  async def redirect_to_docs():
    return HTMLResponse(
      status_code=307, headers={"Location": docs.router.prefix + "/"}
    )

  prefix = "" if settings.api_prefix == "/" else settings.api_prefix

  app.include_router(health.router, prefix=prefix)
  app.include_router(docs.router, prefix=prefix)
  app.mount(prefix, mcp_server.streamable_http_app(), name="mcp")

  return app
