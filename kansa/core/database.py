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
import fcntl
import json
import logging
import os
import shutil
import sqlite3
import tarfile
import uuid
from collections import OrderedDict
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx

from kansa.core.settings import Settings

logger = logging.getLogger(__name__)

DATABASE_NAME = "podcastindex_feeds.db"
DATABASE_LOCK_NAME = f"{DATABASE_NAME}.lock"
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
    self.lock_path = self.data_path / DATABASE_LOCK_NAME
    self.episode_cache_path = self.data_path / "episodes_cache.db"
    self._lock = asyncio.Lock()
    self._cache_lock = asyncio.Lock()
    self._episode_cache_lock = asyncio.Lock()
    self._task: asyncio.Task[None] | None = None
    self._generation = 0
    self._database_signature: tuple[int, int] | None = None
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
      logger.info("Podcast database is missing; starting initial installation")
      await self._install_missing_database()

    if self.settings.database_search_index_enabled:
      logger.info("Preparing podcast database search indexes")
      await asyncio.to_thread(self._prepare_search_indexes_locked, self.path)

    logger.info("Preparing podcast episode cache")
    await asyncio.to_thread(self._prepare_cache)
    await self._refresh_database_signature()

    if self.settings.database_auto_update:
      self._task = asyncio.create_task(
        self._update_loop(),
        name="podcast-database-updater",
      )

  async def start_episode_cache(self) -> None:
    """Prepare only the episode cache for API-backed catalog mode."""
    self.data_path.mkdir(parents=True, exist_ok=True)
    logger.info("Preparing podcast episode cache")
    await asyncio.to_thread(self._prepare_cache)

  async def close(self) -> None:
    """Stop the background updater."""
    if self._task:
      self._task.cancel()

      with contextlib.suppress(asyncio.CancelledError):
        await self._task

  async def update(self) -> None:
    """Download, validate, and atomically replace the database."""
    async with self._lock:
      logger.info("Starting podcast database update")
      await self._replace_database()

  async def _install_missing_database(self) -> None:
    """Install the shared database once when several replicas start together."""
    async with self._lock:
      with self._database_lock():
        if self.path.is_file():
          logger.info("Using database installed by another replica")
          return

      logger.info("Installing shared podcast database")
      await self._replace_database()

  async def _replace_database(self) -> None:
    started = perf_counter()
    token = f"{os.getpid()}-{uuid.uuid4().hex}"
    archive = self.data_path / f"{DATABASE_NAME}.{token}.download"
    replacement = self.data_path / f"{DATABASE_NAME}.{token}.new"

    try:
      logger.info(f"Downloading podcast database: url={self.settings.database_download_url}")
      downloaded_bytes = 0

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
            downloaded_bytes += len(chunk)
            output.write(chunk)

      logger.info(
        "Podcast database download complete: bytes=%d duration_ms=%.1f",
        downloaded_bytes,
        (perf_counter() - started) * 1000,
      )

      extract_started = perf_counter()
      logger.info("Extracting podcast database archive")

      await asyncio.to_thread(self._extract, archive, replacement)
      logger.info(
        "Podcast database archive extracted: bytes=%d duration_ms=%.1f",
        replacement.stat().st_size,
        (perf_counter() - extract_started) * 1000,
      )

      validate_started = perf_counter()
      logger.info("Validating podcast database snapshot")
      await asyncio.to_thread(self._validate, replacement)
      logger.info(
        "Podcast database snapshot validated: duration_ms=%.1f",
        (perf_counter() - validate_started) * 1000,
      )

      if self.settings.database_search_index_enabled:
        index_started = perf_counter()
        logger.info("Preparing search indexes for new podcast database")
        await asyncio.to_thread(self._prepare_search_indexes, replacement)
        logger.info(
          "Search indexes prepared for new podcast database: duration_ms=%.1f",
          (perf_counter() - index_started) * 1000,
        )
      else:
        logger.info("Skipping podcast search indexes; disabled by settings")

      with self._database_lock():
        logger.info("Replacing shared podcast database snapshot")
        os.replace(replacement, self.path)

      await self._refresh_database_signature()
      logger.info(
        "Podcast database update complete: path=%s duration_ms=%.1f",
        self.path,
        (perf_counter() - started) * 1000,
      )
    except (httpx.HTTPError, OSError, tarfile.TarError, sqlite3.Error) as exc:
      logger.exception("Podcast database update failed")
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
    await self._refresh_database_signature()
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

  async def _refresh_database_signature(self) -> None:
    signature = await asyncio.to_thread(self._database_signature_for_path)

    async with self._cache_lock:
      if signature == self._database_signature:
        return

      self._database_signature = signature
      self._generation += 1
      self._query_cache.clear()

  def _database_signature_for_path(self) -> tuple[int, int] | None:
    try:
      stat = self.path.stat()
    except FileNotFoundError:
      return None

    return stat.st_mtime_ns, stat.st_size

  @contextmanager
  def _database_lock(self) -> Generator[None]:
    self.lock_path.parent.mkdir(parents=True, exist_ok=True)

    with self.lock_path.open("a+b") as lock_file:
      fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

      try:
        yield
      finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

  @staticmethod
  def _extract(archive_path: Path, output_path: Path) -> None:
    with tarfile.open(archive_path, "r:gz") as archive:
      member = next(
        (item for item in archive.getmembers() if Path(item.name).name == DATABASE_NAME and item.isfile()),
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
    with sqlite3.connect(
      f"file:{path}?mode=ro",
      timeout=30,
      uri=True,
    ) as connection:
      check = connection.execute("PRAGMA quick_check").fetchone()

      if not check or check[0] != "ok":
        raise sqlite3.DatabaseError("Database integrity check failed")

      columns = {row[1] for row in connection.execute("PRAGMA table_info(podcasts)")}

      if not REQUIRED_COLUMNS.issubset(columns):
        raise sqlite3.DatabaseError("Unsupported database schema")

  def _rows(
    self,
    sql: str,
    parameters: tuple[Any, ...],
  ) -> list[dict[str, Any]]:
    with sqlite3.connect(
      f"file:{self.path}?mode=ro",
      timeout=30,
      uri=True,
    ) as connection:
      connection.row_factory = sqlite3.Row

      return [dict(row) for row in connection.execute(sql, parameters)]

  @staticmethod
  def _prepare_search_indexes(path: Path) -> None:
    """Build persistent indexes once for each downloaded snapshot."""
    with sqlite3.connect(path, timeout=30) as connection:
      connection.execute("PRAGMA busy_timeout = 30000")
      connection.execute("PRAGMA temp_store = MEMORY")
      connection.execute("CREATE TABLE IF NOT EXISTS kansa_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
      version = connection.execute("SELECT value FROM kansa_metadata WHERE key = 'search_schema'").fetchone()

      if version and version[0] == "2":
        return

      logger.info("Building persistent podcast search indexes")
      connection.execute(
        "CREATE INDEX IF NOT EXISTS kansa_rank_idx ON podcasts (dead, popularityScore DESC, newestItemPubdate DESC)"
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
      connection.execute("INSERT INTO podcasts_fts(podcasts_fts) VALUES('rebuild')")
      connection.execute("INSERT OR REPLACE INTO kansa_metadata(key, value) VALUES('search_schema', '2')")
      connection.execute("PRAGMA optimize")
      logger.info("Podcast search indexes are ready")

  def _prepare_search_indexes_locked(self, path: Path) -> None:
    with self._database_lock():
      self._prepare_search_indexes(path)

  def _prepare_cache(self) -> None:
    with sqlite3.connect(self.episode_cache_path, timeout=30) as connection:
      connection.execute("PRAGMA busy_timeout = 30000")
      columns = connection.execute("PRAGMA table_info(episodes)").fetchall()
      column_names = [column[1] for column in columns]

      if columns and column_names != ["id", "payload"]:
        logger.info(
          "Migrating legacy episode cache schema: columns=%s",
          column_names,
        )
        connection.execute("DROP TABLE IF EXISTS episodes_legacy")
        connection.execute("ALTER TABLE episodes RENAME TO episodes_legacy")

      connection.execute("CREATE TABLE IF NOT EXISTS episodes (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")

      if columns and column_names != ["id", "payload"]:
        if {"id", "payload"}.issubset(column_names):
          connection.execute(
            "INSERT OR REPLACE INTO episodes (id, payload) "
            "SELECT CAST(id AS INTEGER), payload FROM episodes_legacy "
            "WHERE payload IS NOT NULL"
          )

        connection.execute("DROP TABLE episodes_legacy")

  def _cache_episodes(self, episodes: list[dict[str, Any]]) -> None:
    with sqlite3.connect(self.episode_cache_path, timeout=30) as connection:
      connection.execute("PRAGMA busy_timeout = 30000")
      connection.executemany(
        "INSERT OR REPLACE INTO episodes (id, payload) VALUES (?, ?)",
        [(item["id"], json.dumps(item, ensure_ascii=False)) for item in episodes],
      )

  def _cached_episode(self, episode_id: int) -> dict[str, Any] | None:
    with sqlite3.connect(self.episode_cache_path, timeout=30) as connection:
      connection.execute("PRAGMA busy_timeout = 30000")
      row = connection.execute(
        "SELECT payload FROM episodes WHERE id = ?",
        (episode_id,),
      ).fetchone()

    return json.loads(row[0]) if row else None
