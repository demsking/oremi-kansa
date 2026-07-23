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
import hashlib
import logging
import time
import zlib
from typing import Any

import httpx

from kansa.core.models import PodcastCategory
from kansa.core.settings import Settings

logger = logging.getLogger(__name__)

_PODCAST_TYPES = {"episodic", "serial"}
_PODCAST_MEDIA = {
  "podcast",
  "music",
  "video",
  "film",
  "audiobook",
  "newsletter",
  "blog",
  "podcastL",
  "musicL",
  "videoL",
  "filmL",
  "audiobookL",
  "newsletterL",
  "blogL",
  "mixed",
}


class PodcastIndexClient:
  """Small authenticated client for the public Podcast Index API."""

  def __init__(
    self,
    settings: Settings,
    http_client: httpx.AsyncClient,
  ) -> None:
    self.settings = settings
    self.http_client = http_client

  def _headers(self) -> dict[str, str]:
    if not self.settings.podcast_index_api_key:
      raise RuntimeError("OREMI_KANSA_PODCAST_INDEX_API_KEY is required")

    if not self.settings.podcast_index_api_secret:
      raise RuntimeError("OREMI_KANSA_PODCAST_INDEX_API_SECRET is required")

    timestamp = str(int(time.time()))
    authorization = hashlib.sha1(
      (
        self.settings.podcast_index_api_key
        + self.settings.podcast_index_api_secret
        + timestamp
      ).encode(),
      usedforsecurity=False,
    ).hexdigest()

    return {
      "User-Agent": self.settings.user_agent,
      "X-Auth-Date": timestamp,
      "X-Auth-Key": self.settings.podcast_index_api_key,
      "Authorization": authorization,
    }

  async def start(self) -> None:
    """Validate API backend configuration without doing remote work."""
    self._headers()

  async def close(self) -> None:
    """Keep the same lifecycle surface as the local database backend."""

  async def search_podcasts(
    self,
    query: str,
    language: str | None,
    category: str | None,
    explicit: bool | None,
    limit: int,
  ) -> list[dict[str, Any]]:
    data = await self._get(
      "/search/byterm",
      {
        "q": query,
        "max": limit,
        "fulltext": "",
      },
    )
    feeds = list(data.get("feeds") or [])

    return self._feed_list(
      feeds,
      language=language,
      category=category,
      explicit=explicit,
      limit=limit,
    )

  async def get_podcast(self, feed_id: int) -> dict[str, Any] | None:
    data = await self._get("/podcasts/byfeedid", {"id": feed_id})
    feed = data.get("feed")

    return self._feed_data(feed) if isinstance(feed, dict) else None

  async def get_episode(self, episode_id: int) -> dict[str, Any] | None:
    data = await self._get("/episodes/byid", {"id": episode_id})
    episode = self._episode_from_response(data)

    if not isinstance(episode, dict):
      logger.warning(
        "Podcast Index episode lookup returned no episode: id=%s keys=%s",
        episode_id,
        sorted(data),
      )

    return self._episode_data(episode) if isinstance(episode, dict) else None

  async def trending_podcasts(
    self,
    language: str | None,
    category: str | None,
    limit: int,
  ) -> list[dict[str, Any]]:
    parameters: dict[str, Any] = {"max": limit}

    if language:
      parameters["lang"] = language

    if category:
      parameters["cat"] = category

    data = await self._get("/podcasts/trending", parameters)

    return self._feed_list(data.get("feeds") or [], limit=limit)

  async def categories(self) -> list[PodcastCategory]:
    data = await self._get("/categories/list")
    raw = data.get("feeds") or data.get("categories") or {}

    if isinstance(raw, dict):
      return [
        PodcastCategory(id=int(category_id), name=name)
        for category_id, name in raw.items()
      ]

    return [
      PodcastCategory.model_validate(category)
      for category in raw
      if isinstance(category, dict)
    ]

  async def _get(
    self,
    path: str,
    parameters: dict[str, Any] | None = None,
  ) -> dict[str, Any]:
    try:
      response = await self.http_client.get(
        f"{self.settings.podcast_index_api_base_url}{path}",
        params=parameters or {},
        headers=self._headers(),
      )
      response.raise_for_status()
    except httpx.HTTPStatusError as exc:
      logger.warning(
        "Podcast Index API request failed: path=%s status=%s body=%s",
        path,
        exc.response.status_code,
        exc.response.text[:500],
      )
      raise

    data = response.json()

    if not isinstance(data, dict):
      raise RuntimeError("Podcast Index API returned malformed data")

    return data

  @staticmethod
  def _episode_from_response(data: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("episode", "item", "feed"):
      value = data.get(key)

      if isinstance(value, dict):
        return value

    episodes = data.get("episodes")

    if isinstance(episodes, list):
      return next((item for item in episodes if isinstance(item, dict)), None)

    return None

  @staticmethod
  def _feed_list(
    feeds: object,
    limit: int,
    language: str | None = None,
    category: str | None = None,
    explicit: bool | None = None,
  ) -> list[dict[str, Any]]:
    if not isinstance(feeds, list):
      return []

    result: list[dict[str, Any]] = []

    for feed in feeds:
      if not isinstance(feed, dict):
        continue

      if not PodcastIndexClient._matches_filters(
        feed,
        language,
        category,
        explicit,
      ):
        continue

      data = PodcastIndexClient._feed_data(feed)

      if data["id"] and data["title"]:
        result.append(data)

      if len(result) >= limit:
        break

    return result

  @staticmethod
  def _feed_data(feed: dict[str, Any]) -> dict[str, Any]:
    podcast_type = PodcastIndexClient._known_value(
      feed.get("type"),
      _PODCAST_TYPES,
    )
    medium = PodcastIndexClient._known_value(feed.get("medium"), _PODCAST_MEDIA)

    return {
      **feed,
      "id": PodcastIndexClient._positive_int(feed.get("id")),
      "title": str(feed.get("title") or "").strip(),
      "url": PodcastIndexClient._non_empty(feed.get("url")),
      "link": PodcastIndexClient._non_empty(feed.get("link")),
      "description": PodcastIndexClient._non_empty(feed.get("description")),
      "author": PodcastIndexClient._non_empty(feed.get("author")),
      "ownerName": PodcastIndexClient._non_empty(feed.get("ownerName")),
      "image": PodcastIndexClient._non_empty(feed.get("image")),
      "artwork": PodcastIndexClient._non_empty(feed.get("artwork")),
      "language": PodcastIndexClient._non_empty(feed.get("language")),
      "explicit": PodcastIndexClient._optional_bool(feed.get("explicit")),
      "type": podcast_type,
      "medium": medium,
      "episodeCount": PodcastIndexClient._positive_int(
        feed.get("episodeCount")
      ),
      "newestItemPublishTime": PodcastIndexClient._positive_int(
        feed.get("newestItemPublishTime")
      ),
      "categories": PodcastIndexClient._categories(feed.get("categories")),
      "itunesId": PodcastIndexClient._positive_int(feed.get("itunesId")),
      "lastUpdateTime": PodcastIndexClient._positive_int(
        feed.get("lastUpdateTime")
      ),
    }

  @staticmethod
  def _episode_data(episode: dict[str, Any]) -> dict[str, Any]:
    return {
      **episode,
      "id": PodcastIndexClient._positive_int(episode.get("id")),
      "title": str(episode.get("title") or "").strip(),
      "feedId": PodcastIndexClient._positive_int(episode.get("feedId")),
      "feedTitle": PodcastIndexClient._non_empty(episode.get("feedTitle")),
      "description": PodcastIndexClient._non_empty(episode.get("description")),
      "link": PodcastIndexClient._non_empty(episode.get("link")),
      "guid": PodcastIndexClient._non_empty(episode.get("guid")),
      "datePublished": PodcastIndexClient._positive_int(
        episode.get("datePublished")
      ),
      "duration": PodcastIndexClient._positive_int(episode.get("duration")),
      "enclosureUrl": PodcastIndexClient._non_empty(
        episode.get("enclosureUrl")
      ),
      "enclosureType": PodcastIndexClient._non_empty(
        episode.get("enclosureType")
      ),
      "image": PodcastIndexClient._non_empty(episode.get("image")),
      "explicit": PodcastIndexClient._optional_bool(episode.get("explicit")),
      "transcriptUrl": PodcastIndexClient._non_empty(
        episode.get("transcriptUrl")
      ),
      "chaptersUrl": PodcastIndexClient._non_empty(episode.get("chaptersUrl")),
      "season": PodcastIndexClient._positive_int(episode.get("season")),
      "episode": PodcastIndexClient._positive_int(episode.get("episode")),
      "episodeType": PodcastIndexClient._non_empty(episode.get("episodeType")),
    }

  @staticmethod
  def _known_value(value: object, allowed: set[str]) -> str | None:
    if not isinstance(value, str):
      return None

    stripped = value.strip()
    return stripped if stripped in allowed else None

  @staticmethod
  def _non_empty(value: object) -> str | None:
    if not isinstance(value, str):
      return None

    stripped = value.strip()
    return stripped or None

  @staticmethod
  def _positive_int(value: object) -> int | None:
    try:
      normalized = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError, OverflowError):
      return None

    return normalized if normalized > 0 else None

  @staticmethod
  def _optional_bool(value: object) -> bool | None:
    if value is None:
      return None

    if isinstance(value, bool):
      return value

    if isinstance(value, int):
      return bool(value)

    if isinstance(value, str):
      normalized = value.strip().casefold()

      if normalized in {"1", "true", "yes"}:
        return True

      if normalized in {"0", "false", "no"}:
        return False

    return None

  @staticmethod
  def _categories(value: object) -> list[dict[str, object]]:
    if not value:
      return []

    if isinstance(value, dict):
      categories: list[dict[str, object]] = []

      for key, name_or_id in value.items():
        if str(key).isdigit():
          category_id = int(key)
          name = str(name_or_id).strip()
        elif str(name_or_id).isdigit():
          category_id = int(name_or_id)
          name = str(key).strip()
        else:
          name = str(name_or_id or key).strip()
          category_id = zlib.crc32(name.casefold().encode()) or 1

        if name:
          categories.append({"id": category_id, "name": name})

      return categories

    if isinstance(value, list):
      return [
        item
        for item in value
        if isinstance(item, dict) and item.get("id") and item.get("name")
      ]

    return []

  @staticmethod
  def _matches_filters(
    feed: dict[str, Any],
    language: str | None,
    category: str | None,
    explicit: bool | None,
  ) -> bool:
    if language:
      feed_language = str(feed.get("language") or "").casefold()
      wanted_language = language.casefold()

      if feed_language not in {wanted_language, f"{wanted_language}-"}:
        if not feed_language.startswith(f"{wanted_language}-"):
          return False

    if category:
      category_names = {
        str(item["name"]).casefold()
        for item in PodcastIndexClient._categories(feed.get("categories"))
      }

      if category.casefold() not in category_names:
        return False

    if explicit is not None and feed.get("explicit") is not None:
      if bool(feed["explicit"]) is not explicit:
        return False

    return True
