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
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic import field_validator
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

from kansa.core.package import APP_NAME
from kansa.core.package import APP_VERSION


class Settings(BaseSettings):
  """Application and Podcast Index API settings."""

  model_config = SettingsConfigDict(
    env_prefix="OREMI_KANSA_",
    strict=True,
    extra="ignore",
  )

  server_host: str = Field(
    default="127.0.0.1",
    description="HTTP server bind address.",
  )

  server_port: int = Field(
    default=5046,
    ge=1,
    le=65535,
    description="HTTP server port.",
  )

  api_prefix: str = Field(
    default="/",
    description="Base path for all HTTP endpoints.",
  )

  user_agent: str = Field(
    default=f"{APP_NAME}/{APP_VERSION}",
    min_length=1,
    description="Application identifier sent to Podcast Index.",
  )

  catalog_backend: Literal["database", "api"] = Field(
    default="database",
    description="Podcast catalog backend: local database or Podcast Index API.",
  )

  podcast_index_api_base_url: str = Field(
    default="https://api.podcastindex.org/api/1.0",
    min_length=1,
    description="Podcast Index API base URL.",
  )

  podcast_index_api_key: str | None = Field(
    default=None,
    description="Podcast Index API key for API backend mode.",
  )

  podcast_index_api_secret: str | None = Field(
    default=None,
    description="Podcast Index API secret for API backend mode.",
  )

  database_download_url: str = Field(
    default="https://public.podcastindex.org/podcastindex_feeds.db.tgz",
    min_length=1,
    description="Offline Podcast Index database archive URL.",
  )

  data_path: Path = Field(
    default=None,  # type: ignore
    description="Podcast database and episode cache directory.",
  )

  database_auto_update: bool = Field(
    default=True,
    description="Enable periodic offline database updates.",
  )

  database_update_interval_hours: float = Field(
    default=24.0,
    gt=0,
    description="Hours between offline database update attempts.",
  )

  database_search_index_enabled: bool = Field(
    default=True,
    description="Build persistent FTS and ranking indexes.",
  )

  query_cache_size: int = Field(
    default=256,
    ge=0,
    le=4096,
    description="Maximum database query results retained in memory.",
  )

  http_connect_timeout: float = Field(
    default=5.0,
    gt=0,
    description="HTTP connection timeout in seconds.",
  )

  http_read_timeout: float = Field(
    default=15.0,
    gt=0,
    description="HTTP response read timeout in seconds.",
  )

  http_write_timeout: float = Field(
    default=5.0,
    gt=0,
    description="HTTP request write timeout in seconds.",
  )

  http_pool_timeout: float = Field(
    default=5.0,
    gt=0,
    description="HTTP connection pool timeout in seconds.",
  )

  log_level: Literal[
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
  ] = Field(default="INFO")

  log_file: str | None = Field(
    default=None,
    description="Optional rotating log file path.",
  )

  @field_validator("data_path", mode="before")
  @classmethod
  def validate_data_path(cls, value) -> Path:
    if value is not None:
      return Path(value)

    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME

  @field_validator("api_prefix")
  @classmethod
  def validate_api_prefix(cls, value: str) -> str:
    if not value.startswith("/"):
      raise ValueError("OREMI_KANSA_API_PREFIX must start with '/'")
    return value.rstrip("/") or "/"

  @field_validator("podcast_index_api_base_url")
  @classmethod
  def validate_podcast_index_api_base_url(cls, value: str) -> str:
    return value.rstrip("/")


@lru_cache
def get_settings() -> Settings:
  """Return cached application settings."""
  return Settings()  # pyright: ignore
