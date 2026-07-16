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
import asyncio
import contextlib
import json
import logging
import os
import shutil
import sqlite3
import tarfile
from collections import OrderedDict
from pathlib import Path
from typing import Any

import httpx

from .settings import Settings

logger = logging.getLogger(__name__)

DATABASE_NAME = "podcastindex_feeds.db"
CATEGORY_COLUMNS = tuple(f"category{number}" for number in range(1, 11))
REQUIRED_COLUMNS = {
  "id",
  "url",
  "title",
  "language",
  "description",
  "popularityScore",
  *CATEGORY_COLUMNS,
}


class PodcastDatabase:
  """Manage and query the offline Podcast Index database."""

  def __init__(
    self,
    settings: Settings,
    http_client: httpx.AsyncClient,
  ) -> None:
    self.settings = settings
    self.http_client = http_client
    self.data_path = Path(settings.data_path)
    self.path = self.data_path / DATABASE_NAME
    self.episode_cache_path = self.data_path / "episodes_cache.db"
    self._lock = asyncio.Lock()
    self._cache_lock = asyncio.Lock()
    self._episode_cache_lock = asyncio.Lock()
    self._task: asyncio.Task[None] | None = None
    self._generation = 0
    self._query_cache: OrderedDict[
      tuple[str, tuple[Any, ...]],
      list[dict[str, Any]],
    ] = OrderedDict()

  async def start(self) -> None:
    """Install the database when absent and start optional updates."""
    self.data_path.mkdir(parents=True, exist_ok=True)
    needs_download = not self.path.is_file()

    if not needs_download:
      logger.info(f"Loading database file:{self.path}")

      try:
        await asyncio.to_thread(self._validate, self.path)
      except sqlite3.Error:
        logger.exception("The local podcast database is invalid")
        needs_download = True

    if needs_download:
      await self.update()

    if self.settings.database_search_index_enabled:
      await asyncio.to_thread(self._prepare_search_indexes, self.path)

    await asyncio.to_thread(self._prepare_cache)

    if self.settings.database_auto_update:
      self._task = asyncio.create_task(
        self._update_loop(),
        name="podcast-database-updater",
      )

  async def close(self) -> None:
    """Stop the background updater."""
    if self._task:
      self._task.cancel()

      with contextlib.suppress(asyncio.CancelledError):
        await self._task

  async def update(self) -> None:
    """Download, validate, and atomically replace the database."""
    async with self._lock:
      archive = self.data_path / f"{DATABASE_NAME}.download"
      replacement = self.data_path / f"{DATABASE_NAME}.new"

      try:
        async with self.http_client.stream(
          "GET",
          self.settings.database_download_url,
          headers={"User-Agent": self.settings.user_agent},
          timeout=httpx.Timeout(
            connect=self.settings.http_connect_timeout,
            read=None,
            write=self.settings.http_write_timeout,
            pool=self.settings.http_pool_timeout,
          ),
        ) as response:
          response.raise_for_status()
          with archive.open("wb") as output:
            async for chunk in response.aiter_bytes(1024 * 1024):
              output.write(chunk)

        await asyncio.to_thread(self._extract, archive, replacement)
        await asyncio.to_thread(self._validate, replacement)

        if self.settings.database_search_index_enabled:
          await asyncio.to_thread(
            self._prepare_search_indexes,
            replacement,
          )

        os.replace(replacement, self.path)
        async with self._cache_lock:
          self._generation += 1
          self._query_cache.clear()
      except (httpx.HTTPError, OSError, tarfile.TarError, sqlite3.Error) as exc:
        raise RuntimeError("Could not update the podcast database") from exc
      finally:
        archive.unlink(missing_ok=True)
        replacement.unlink(missing_ok=True)

  async def rows(
    self,
    sql: str,
    parameters: tuple[Any, ...] = (),
  ) -> list[dict[str, Any]]:
    """Run a read-only query outside the event loop."""
    key = (sql, parameters)
    generation = self._generation

    if self.settings.query_cache_size:
      async with self._cache_lock:
        cached = self._query_cache.get(key)

        if cached is not None:
          self._query_cache.move_to_end(key)
          return [row.copy() for row in cached]

    try:
      result = await asyncio.to_thread(self._rows, sql, parameters)
    except sqlite3.Error as exc:
      raise RuntimeError("The podcast database query failed") from exc

    if self.settings.query_cache_size:
      async with self._cache_lock:
        if generation != self._generation:
          return result

        self._query_cache[key] = [row.copy() for row in result]
        self._query_cache.move_to_end(key)

        while len(self._query_cache) > self.settings.query_cache_size:
          self._query_cache.popitem(last=False)

    return result

  async def cache_episodes(self, episodes: list[dict[str, Any]]) -> None:
    async with self._episode_cache_lock:
      await asyncio.to_thread(self._prepare_cache)
      await asyncio.to_thread(self._cache_episodes, episodes)

  async def cached_episode(self, episode_id: int) -> dict[str, Any] | None:
    async with self._episode_cache_lock:
      await asyncio.to_thread(self._prepare_cache)
      return await asyncio.to_thread(self._cached_episode, episode_id)

  async def _update_loop(self) -> None:
    interval = self.settings.database_update_interval_hours * 3600
    while True:
      await asyncio.sleep(interval)

      try:
        await self.update()
      except Exception:
        logger.exception("Automatic podcast database update failed")

  @staticmethod
  def _extract(archive_path: Path, output_path: Path) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
      member = next(
        (
          item
          for item in archive.getmembers()
          if Path(item.name).name == DATABASE_NAME and item.isfile()
        ),
        None,
      )

      if member is None:
        raise tarfile.ReadError("Database archive has no database")

      source = archive.extractfile(member)

      if source is None:
        raise tarfile.ReadError("Database archive is unreadable")

      with source, output_path.open("wb") as output:
        shutil.copyfileobj(source, output, length=1024 * 1024)

  @staticmethod
  def _validate(path: Path) -> None:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
      check = connection.execute("PRAGMA quick_check").fetchone()

      if not check or check[0] != "ok":
        raise sqlite3.DatabaseError("Database integrity check failed")

      columns = {
        row[1] for row in connection.execute("PRAGMA table_info(podcasts)")
      }

      if not REQUIRED_COLUMNS.issubset(columns):
        raise sqlite3.DatabaseError("Unsupported database schema")

  def _rows(
    self,
    sql: str,
    parameters: tuple[Any, ...],
  ) -> list[dict[str, Any]]:
    with sqlite3.connect(f"file:{self.path}?mode=ro", uri=True) as connection:
      connection.row_factory = sqlite3.Row

      return [dict(row) for row in connection.execute(sql, parameters)]

  @staticmethod
  def _prepare_search_indexes(path: Path) -> None:
    """Build persistent indexes once for each downloaded snapshot."""
    with sqlite3.connect(path) as connection:
      connection.execute("PRAGMA temp_store = MEMORY")
      connection.execute(
        "CREATE TABLE IF NOT EXISTS kansa_metadata ("
        "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
      )
      version = connection.execute(
        "SELECT value FROM kansa_metadata WHERE key = 'search_schema'"
      ).fetchone()

      if version and version[0] == "2":
        return

      logger.info("Building persistent podcast search indexes")
      connection.execute(
        "CREATE INDEX IF NOT EXISTS kansa_rank_idx ON podcasts ("
        "dead, popularityScore DESC, newestItemPubdate DESC)"
      )
      connection.execute(
        "CREATE INDEX IF NOT EXISTS kansa_language_rank_v2_idx ON podcasts ("
        "language COLLATE NOCASE, dead, popularityScore DESC, "
        "newestItemPubdate DESC)"
      )
      connection.execute(
        "CREATE INDEX IF NOT EXISTS kansa_explicit_rank_idx ON podcasts ("
        "explicit, dead, popularityScore DESC, newestItemPubdate DESC)"
      )

      for column in CATEGORY_COLUMNS:
        connection.execute(
          f"CREATE INDEX IF NOT EXISTS kansa_{column}_rank_v2_idx "
          f"ON podcasts ({column} COLLATE NOCASE, dead, "
          "popularityScore DESC, "
          "newestItemPubdate DESC)"
        )

      connection.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS podcasts_fts USING fts5("
        "title, description, itunesAuthor, content='podcasts', "
        "content_rowid='id', tokenize='unicode61 remove_diacritics 2')"
      )
      connection.execute(
        "INSERT INTO podcasts_fts(podcasts_fts) VALUES('rebuild')"
      )
      connection.execute(
        "INSERT OR REPLACE INTO kansa_metadata(key, value) "
        "VALUES('search_schema', '2')"
      )
      connection.execute("PRAGMA optimize")
      logger.info("Podcast search indexes are ready")

  def _prepare_cache(self) -> None:
    with sqlite3.connect(self.episode_cache_path) as connection:
      columns = connection.execute("PRAGMA table_info(episodes)").fetchall()
      column_names = [column[1] for column in columns]

      if columns and column_names != ["id", "payload"]:
        logger.info(
          "Migrating legacy episode cache schema: columns=%s",
          column_names,
        )
        connection.execute("DROP TABLE IF EXISTS episodes_legacy")
        connection.execute("ALTER TABLE episodes RENAME TO episodes_legacy")

      connection.execute(
        "CREATE TABLE IF NOT EXISTS episodes ("
        "id INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
      )

      if columns and column_names != ["id", "payload"]:
        if {"id", "payload"}.issubset(column_names):
          connection.execute(
            "INSERT OR REPLACE INTO episodes (id, payload) "
            "SELECT CAST(id AS INTEGER), payload FROM episodes_legacy "
            "WHERE payload IS NOT NULL"
          )

        connection.execute("DROP TABLE episodes_legacy")

  def _cache_episodes(self, episodes: list[dict[str, Any]]) -> None:
    with sqlite3.connect(self.episode_cache_path) as connection:
      connection.executemany(
        "INSERT OR REPLACE INTO episodes (id, payload) VALUES (?, ?)",
        [
          (item["id"], json.dumps(item, ensure_ascii=False))
          for item in episodes
        ],
      )

  def _cached_episode(self, episode_id: int) -> dict[str, Any] | None:
    with sqlite3.connect(self.episode_cache_path) as connection:
      row = connection.execute(
        "SELECT payload FROM episodes WHERE id = ?",
        (episode_id,),
      ).fetchone()

    return json.loads(row[0]) if row else None
