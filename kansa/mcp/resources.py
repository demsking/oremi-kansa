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
import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError

from kansa.core.database import PodcastDatabase
from kansa.core.feeds import fetch_episodes
from kansa.core.models import EpisodeDetails
from kansa.core.models import EpisodeSummary
from kansa.core.models import PodcastCategory
from kansa.core.models import PodcastDetails
from kansa.core.podcast_index import PodcastIndexClient
from kansa.core.settings import Settings
from kansa.mcp.tools import _CATEGORIES_SQL
from kansa.mcp.tools import _category_id
from kansa.mcp.tools import _podcast_data


def register_mcp_resources(
  mcp: MCPServer,
  settings: Settings,
  database: PodcastDatabase,
  podcast_index: PodcastIndexClient,
  http_client: httpx.AsyncClient,
) -> None:
  """Register MCP resources for accessing podcast catalog data directly."""
  using_api = settings.catalog_backend == "api"

  async def get_podcast_details(feed_id: int) -> PodcastDetails:
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

  async def get_podcast_episodes(feed: PodcastDetails) -> list[EpisodeSummary]:
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

  @mcp.resource("podcasts:///{feed_id}/details", mime_type="application/json")
  async def get_podcast_details_resource(feed_id: str) -> PodcastDetails:
    """Retrieve detailed metadata for a specific podcast by feed ID."""
    try:
      fid = int(feed_id)
    except ValueError as error:
      raise ToolError("Feed ID must be a positive integer") from error

    return await get_podcast_details(fid)

  @mcp.resource("podcasts:///{feed_id}/episodes", mime_type="application/json")
  async def get_podcast_episodes_resource(
    feed_id: str,
  ) -> list[EpisodeSummary]:
    """Retrieve the recent episodes for a specific podcast by feed ID."""
    try:
      fid = int(feed_id)
    except ValueError as error:
      raise ToolError("Feed ID must be a positive integer") from error

    feed = await get_podcast_details(fid)

    return await get_podcast_episodes(feed)

  @mcp.resource(
    "episodes:///{episode_id}/details", mime_type="application/json"
  )
  async def get_episode_details_resource(episode_id: str) -> EpisodeDetails:
    """Retrieve detailed metadata for a cached episode or fetch it from API."""
    try:
      epid = int(episode_id)
    except ValueError as error:
      raise ToolError("Episode ID must be a positive integer") from error

    item = await database.cached_episode(epid)

    if item is None:
      if not using_api:
        raise ToolError("Episode not found; list or search episodes first")

      item = await podcast_index.get_episode(epid)

    if item is None:
      raise ToolError("Episode not found")

    try:
      return EpisodeDetails.model_validate(item)
    except ValidationError as exc:
      raise ToolError(f"The episode record is malformed: {exc}") from exc

  @mcp.resource("categories:///list", mime_type="application/json")
  async def list_categories_resource() -> list[PodcastCategory]:
    """Retrieve the list of available categories in the podcast catalog."""
    if using_api:
      return await podcast_index.categories()

    rows = await database.rows(_CATEGORIES_SQL)

    return [
      PodcastCategory(id=_category_id(row["name"]), name=row["name"])
      for row in rows
    ]
