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
import re
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from defusedxml import ElementTree
from mcp.server.mcpserver.exceptions import ToolError

_TAG = re.compile(r"^\{[^}]+\}")


def _name(element: Any) -> str:
  return _TAG.sub("", element.tag).lower()


def _text(element: Any, *names: str) -> str | None:
  for child in element:
    if _name(child) in names and child.text:
      text_val: str = child.text.strip()

      return text_val

  return None


def _timestamp(value: str | None) -> int | None:
  try:
    return int(parsedate_to_datetime(value).timestamp()) if value else None
  except (TypeError, ValueError, OverflowError):
    return None


def _duration(value: str | None) -> int | None:
  if not value:
    return None
  try:
    parts = [int(part) for part in value.split(":")]
  except ValueError:
    return None
  total = 0
  for part in parts:
    total = total * 60 + part
  return total


def parse_feed(
  content: bytes,
  feed_id: int,
  feed_title: str,
) -> list[dict[str, Any]]:
  """Parse RSS or Atom episodes into model-compatible dictionaries."""
  try:
    root = ElementTree.fromstring(content)
  except ElementTree.ParseError as exc:
    raise ToolError("The podcast feed returned invalid XML") from exc
  episodes: list[dict[str, Any]] = []
  for entry in (
    item for item in root.iter() if _name(item) in {"item", "entry"}
  ):
    title = _text(entry, "title")
    guid = _text(entry, "guid", "id")
    link = _text(entry, "link")
    enclosure_url = None
    enclosure_type = None
    for child in entry:
      if _name(child) == "enclosure" or (
        _name(child) == "link" and child.attrib.get("rel") == "enclosure"
      ):
        enclosure_url = child.attrib.get("url") or child.attrib.get("href")
        enclosure_type = child.attrib.get("type")
        break
    identity = guid or enclosure_url or link or title
    if not identity or not title:
      continue
    episode_id = int(
      hashlib.sha256(
        f"{feed_id}:{identity}".encode(),
        usedforsecurity=False,
      ).hexdigest()[:15],
      16,
    )
    episodes.append(
      {
        "id": episode_id,
        "feedId": feed_id,
        "feedTitle": feed_title,
        "title": title,
        "description": _text(entry, "description", "summary", "encoded"),
        "guid": guid,
        "link": link,
        "datePublished": _timestamp(
          _text(entry, "pubdate", "published", "updated")
        ),
        "duration": _duration(_text(entry, "duration")),
        "enclosureUrl": enclosure_url,
        "enclosureType": enclosure_type,
      }
    )
  episodes.sort(key=lambda item: item["datePublished"] or 0, reverse=True)
  return episodes


async def fetch_episodes(
  http_client: httpx.AsyncClient,
  feed: dict[str, Any],
  user_agent: str,
) -> list[dict[str, Any]]:
  """Fetch episodes from the public feed URL stored offline."""
  try:
    response = await http_client.get(
      str(feed["url"]),
      headers={"User-Agent": user_agent},
    )
    response.raise_for_status()
  except httpx.TimeoutException as exc:
    raise ToolError("The podcast feed request timed out") from exc
  except httpx.HTTPError as exc:
    raise ToolError("The podcast feed is unavailable") from exc
  return parse_feed(response.content, int(feed["id"]), str(feed["title"]))
