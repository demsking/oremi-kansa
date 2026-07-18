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
import re
import zlib
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from kansa.core.database import CATEGORY_COLUMNS
from kansa.core.database import PodcastDatabase
from kansa.core.feeds import fetch_episodes
from kansa.core.models import CategoryListResponse
from kansa.core.models import EpisodeDetails
from kansa.core.models import EpisodeListResponse
from kansa.core.models import EpisodeSearchResponse
from kansa.core.models import EpisodeSummary
from kansa.core.models import LanguageCode
from kansa.core.models import NonEmptyString
from kansa.core.models import PodcastCategory
from kansa.core.models import PodcastDetails
from kansa.core.models import PodcastListResponse
from kansa.core.models import PodcastSearchResponse
from kansa.core.models import PodcastSummary
from kansa.core.models import PositiveId
from kansa.core.models import ResultLimit
from kansa.core.podcast_index import PodcastIndexClient
from kansa.core.settings import Settings

READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True)
_SEARCH_TERM = re.compile(r"[\w]+", re.UNICODE)

_CATEGORY_MATCH_SQL = (
  "p.category1 = ? COLLATE NOCASE OR "
  "p.category2 = ? COLLATE NOCASE OR "
  "p.category3 = ? COLLATE NOCASE OR "
  "p.category4 = ? COLLATE NOCASE OR "
  "p.category5 = ? COLLATE NOCASE OR "
  "p.category6 = ? COLLATE NOCASE OR "
  "p.category7 = ? COLLATE NOCASE OR "
  "p.category8 = ? COLLATE NOCASE OR "
  "p.category9 = ? COLLATE NOCASE OR "
  "p.category10 = ? COLLATE NOCASE"
)

_CATEGORIES_SQL = (
  "SELECT name FROM ("
  "SELECT category1 AS name FROM podcasts WHERE category1 != '' "
  "UNION SELECT category2 AS name FROM podcasts WHERE category2 != '' "
  "UNION SELECT category3 AS name FROM podcasts WHERE category3 != '' "
  "UNION SELECT category4 AS name FROM podcasts WHERE category4 != '' "
  "UNION SELECT category5 AS name FROM podcasts WHERE category5 != '' "
  "UNION SELECT category6 AS name FROM podcasts WHERE category6 != '' "
  "UNION SELECT category7 AS name FROM podcasts WHERE category7 != '' "
  "UNION SELECT category8 AS name FROM podcasts WHERE category8 != '' "
  "UNION SELECT category9 AS name FROM podcasts WHERE category9 != '' "
  "UNION SELECT category10 AS name FROM podcasts WHERE category10 != ''"
  ") ORDER BY name COLLATE NOCASE"
)


def _category_id(name: str) -> int:
  """Return a stable local identifier for a category name."""
  return zlib.crc32(name.casefold().encode()) or 1


def _podcast_type(value: object) -> str | None:
  """Normalize known database values without exposing invalid enum values."""
  if not isinstance(value, str):
    return None

  normalized = value.strip().casefold()

  if normalized in {"episodic", "serial"}:
    return normalized

  return None


def _positive_int(value: object) -> int | None:
  """Normalize optional numeric database fields."""
  try:
    normalized = int(value)  # type: ignore[arg-type]
  except (TypeError, ValueError, OverflowError):
    return None

  return normalized if normalized > 0 else None


def _podcast_data(row: dict[str, Any]) -> dict[str, Any]:
  categories = [row.get(column) for column in CATEGORY_COLUMNS]

  return {
    "id": row["id"],
    "title": row["title"],
    "url": row.get("url"),
    "link": row.get("link"),
    "description": row.get("description"),
    "author": row.get("itunesAuthor"),
    "ownerName": row.get("itunesOwnerName"),
    "image": row.get("imageUrl"),
    "language": row.get("language"),
    "explicit": bool(row["explicit"])
    if row.get("explicit") is not None
    else None,
    "type": _podcast_type(row.get("itunesType")),
    "episodeCount": row.get("episodeCount"),
    "newestItemPublishTime": row.get("newestItemPubdate"),
    "categories": [
      {"id": _category_id(name), "name": name} for name in categories if name
    ],
    "guid": row.get("podcastGuid"),
    "itunesId": _positive_int(row.get("itunesId")),
    "originalUrl": row.get("originalUrl"),
    "lastUpdateTime": row.get("lastUpdate"),
  }


def register_mcp_tools(
  mcp: FastMCP,
  settings: Settings,
  database: PodcastDatabase,
  podcast_index: PodcastIndexClient,
  http_client: httpx.AsyncClient,
) -> None:
  """Build an MCP server backed by the configured podcast catalog."""
  using_api = settings.catalog_backend == "api"

  async def podcast(feed_id: int) -> PodcastDetails:
    if using_api:
      feed = await podcast_index.get_podcast(feed_id)

      if not feed:
        raise ToolError("Podcast not found")

      try:
        return PodcastDetails.model_validate(feed)
      except ValidationError as exc:
        raise ToolError("The Podcast Index API record is malformed") from exc

    rows = await database.rows(
      "SELECT * FROM podcasts WHERE id = ? AND id > 0 AND dead = 0 "
      "AND title IS NOT NULL AND TRIM(title) != ''",
      (feed_id,),
    )

    if not rows:
      raise ToolError("Podcast not found")

    try:
      return PodcastDetails.model_validate(_podcast_data(rows[0]))
    except ValidationError as exc:
      raise ToolError("The podcast record is malformed") from exc

  async def search(
    query: str,
    language: str | None,
    category: str | None,
    explicit: bool | None,
    limit: int,
  ) -> list[PodcastSummary]:
    if using_api:
      try:
        if query == "%":
          feeds = await podcast_index.trending_podcasts(
            language,
            category,
            limit,
          )
          if explicit is not None:
            feeds = [
              feed for feed in feeds if feed.get("explicit") is explicit
            ][:limit]
        else:
          feeds = await podcast_index.search_podcasts(
            query,
            language,
            category,
            explicit,
            limit,
          )
        return [PodcastSummary.model_validate(feed) for feed in feeds]
      except ValidationError as exc:
        raise ToolError("The Podcast Index API record is malformed") from exc

    use_fts = query != "%" and settings.database_search_index_enabled
    clauses = [
      "p.id > 0",
      "p.dead = 0",
      "p.title IS NOT NULL",
      "TRIM(p.title) != ''",
    ]
    values: list[Any] = []

    if use_fts:
      terms = _SEARCH_TERM.findall(query.casefold())

      if not terms:
        return []

      clauses.append("podcasts_fts MATCH ?")
      values.append(" AND ".join(f"{term}*" for term in terms))
    elif query != "%":
      clauses.append(
        "(p.title LIKE ? OR p.description LIKE ? OR p.itunesAuthor LIKE ?)"
      )
      pattern = f"%{query}%"
      values.extend([pattern, pattern, pattern])

    if language:
      clauses.append(
        "(p.language = ? COLLATE NOCASE OR p.language LIKE ? COLLATE NOCASE)"
      )
      values.extend([language.lower(), f"{language.lower()}-%"])

    if category:
      clauses.append(f"({_CATEGORY_MATCH_SQL})")
      values.extend([category] * len(CATEGORY_COLUMNS))

    if explicit is not None:
      clauses.append("p.explicit = ?")
      values.append(int(explicit))

    values.append(limit)

    if use_fts:
      query = " ".join(
        (
          "SELECT p.* FROM podcasts p "
          "JOIN podcasts_fts ON podcasts_fts.rowid = p.id WHERE",
          " AND ".join(clauses),
          "ORDER BY p.popularityScore DESC, p.newestItemPubdate DESC LIMIT ?",
        )
      )
    else:
      query = " ".join(
        (
          "SELECT p.* FROM podcasts p WHERE",
          " AND ".join(clauses),
          "ORDER BY p.popularityScore DESC, p.newestItemPubdate DESC LIMIT ?",
        )
      )

    rows = await database.rows(query, tuple(values))

    try:
      return [PodcastSummary.model_validate(_podcast_data(row)) for row in rows]
    except ValidationError as exc:
      raise ToolError("The podcast record is malformed") from exc

  async def categories() -> list[PodcastCategory]:
    if using_api:
      return await podcast_index.categories()

    rows = await database.rows(_CATEGORIES_SQL)

    return [
      PodcastCategory(id=_category_id(row["name"]), name=row["name"])
      for row in rows
    ]

  async def category_name(category_id: int) -> str:
    for category in await categories():
      if category.id == category_id:
        return category.name

    raise ToolError("Category not found")

  async def episodes(feed: PodcastDetails) -> list[EpisodeSummary]:
    raw = await fetch_episodes(
      http_client,
      feed.model_dump(),
      settings.user_agent,
    )

    try:
      result = [EpisodeSummary.model_validate(item) for item in raw]
    except ValidationError as exc:
      raise ToolError("The podcast feed returned malformed data") from exc

    await database.cache_episodes(
      [item.model_dump(by_alias=True) for item in result]
    )

    return result

  @mcp.tool(annotations=READ_ONLY)
  async def search_podcasts(
    query: NonEmptyString,
    language: LanguageCode | None = None,
    category: NonEmptyString | None = None,
    limit: ResultLimit = 10,
  ) -> PodcastSearchResponse:
    """Search the podcast catalog by keyword, language, and category."""
    items = await search(query, language, category, None, limit)

    return PodcastSearchResponse(podcasts=items, count=len(items))

  @mcp.tool(annotations=READ_ONLY)
  async def get_podcast(feed_id: PositiveId) -> PodcastDetails:
    """Retrieve detailed metadata from the podcast catalog."""
    return await podcast(feed_id)

  @mcp.tool(annotations=READ_ONLY)
  async def list_podcast_episodes(
    feed_id: PositiveId,
    limit: ResultLimit = 10,
  ) -> EpisodeListResponse:
    """Retrieve recent episodes using the public feed URL."""
    items = (await episodes(await podcast(feed_id)))[:limit]

    return EpisodeListResponse(episodes=items, count=len(items))

  @mcp.tool(annotations=READ_ONLY)
  async def get_episode(episode_id: PositiveId) -> EpisodeDetails:
    """Retrieve an episode previously stored in the episode cache."""
    item = await database.cached_episode(episode_id)

    if item is None:
      if not using_api:
        raise ToolError("Episode not found; list or search episodes first")

      item = await podcast_index.get_episode(episode_id)

    if item is None:
      raise ToolError("Episode not found")

    try:
      return EpisodeDetails.model_validate(item)
    except ValidationError as exc:
      raise ToolError(f"The episode record is malformed: {exc}") from exc

  @mcp.tool(annotations=READ_ONLY)
  async def search_episodes(
    query: NonEmptyString,
    language: LanguageCode | None = None,
    limit: ResultLimit = 10,
  ) -> EpisodeSearchResponse:
    """Search recent episodes from podcasts matched in the catalog."""
    feeds = await search(query, language, None, None, min(limit, 10))
    details = await asyncio.gather(*(podcast(item.id) for item in feeds))
    results = await asyncio.gather(
      *(episodes(item) for item in details),
      return_exceptions=True,
    )
    terms = query.casefold().split()

    items = [
      item for result in results if isinstance(result, list) for item in result
    ]

    items = [
      item
      for item in items
      if all(
        term in f"{item.title} {item.description or ''}".casefold()
        for term in terms
      )
    ]

    items.sort(key=lambda item: item.date_published or 0, reverse=True)

    items = items[:limit]

    return EpisodeSearchResponse(episodes=items, count=len(items))

  @mcp.tool(annotations=READ_ONLY)
  async def list_categories() -> CategoryListResponse:
    """List categories available in the podcast catalog."""
    items = await categories()

    return CategoryListResponse(categories=items, count=len(items))

  @mcp.tool(annotations=READ_ONLY)
  async def browse_category(
    category_id: PositiveId,
    language: LanguageCode | None = None,
    limit: ResultLimit = 10,
  ) -> PodcastListResponse:
    """Browse popular podcasts in a category."""
    name = await category_name(category_id)
    items = await search("%", language, name, None, limit)

    return PodcastListResponse(podcasts=items, count=len(items))

  @mcp.tool(annotations=READ_ONLY)
  async def trending_podcasts(
    language: LanguageCode | None = None,
    category_id: PositiveId | None = None,
    limit: ResultLimit = 10,
  ) -> PodcastListResponse:
    name = await category_name(category_id) if category_id else None
    if using_api:
      try:
        feeds = await podcast_index.trending_podcasts(language, name, limit)
        items = [PodcastSummary.model_validate(feed) for feed in feeds]
      except ValidationError as exc:
        raise ToolError("The Podcast Index API record is malformed") from exc
    else:
      items = await search("%", language, name, None, limit)

    return PodcastListResponse(podcasts=items, count=len(items))

  @mcp.tool(annotations=READ_ONLY)
  async def similar_podcasts(
    feed_id: PositiveId,
    limit: ResultLimit = 10,
  ) -> PodcastListResponse:
    """Find podcasts sharing categories with a podcast."""
    source = await podcast(feed_id)
    if not source.categories:
      return PodcastListResponse(podcasts=[], count=0)

    items = await search("%", None, source.categories[0].name, None, limit + 1)
    items = [item for item in items if item.id != feed_id][:limit]

    return PodcastListResponse(podcasts=items, count=len(items))

  @mcp.tool(annotations=READ_ONLY)
  async def discover_podcasts(
    topic: NonEmptyString | None = None,
    language: LanguageCode | None = None,
    category_id: PositiveId | None = None,
    explicit: bool | None = None,
    limit: ResultLimit = 10,
  ) -> PodcastListResponse:
    """Discover podcasts using multiple filters."""
    name = await category_name(category_id) if category_id else None
    items = await search(topic or "%", language, name, explicit, limit)

    return PodcastListResponse(podcasts=items, count=len(items))
