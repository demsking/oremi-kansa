import io
import sqlite3
import tarfile
from pathlib import Path

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from kansa.core.database import DATABASE_NAME
from kansa.core.database import PodcastDatabase
from kansa.core.server import _category_id
from kansa.core.server import create_mcp_server
from kansa.core.settings import Settings

SCHEMA = """CREATE TABLE podcasts (
  id INTEGER PRIMARY KEY, url TEXT, title TEXT, link TEXT, dead INTEGER,
  itunesId INTEGER, originalUrl TEXT, itunesAuthor TEXT,
  itunesOwnerName TEXT, explicit INTEGER, imageUrl TEXT, itunesType TEXT,
  newestItemPubdate INTEGER, language TEXT, episodeCount INTEGER,
  popularityScore INTEGER, podcastGuid TEXT, description TEXT,
  lastUpdate INTEGER, category1 TEXT, category2 TEXT, category3 TEXT,
  category4 TEXT, category5 TEXT, category6 TEXT, category7 TEXT,
  category8 TEXT, category9 TEXT, category10 TEXT
)"""


def create_database(path: Path) -> None:
  values = (
    42,
    "https://feeds.example/show.xml",
    "Example Podcast",
    "https://example.test",
    0,
    123,
    "",
    "Author",
    "Owner",
    0,
    "https://example.test/image.jpg",
    "episodic",
    100,
    "en-US",
    2,
    99,
    "guid",
    "A technology testing podcast",
    90,
    "Technology",
    "News",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
  )
  with sqlite3.connect(path) as connection:
    connection.execute(SCHEMA)
    placeholders = ",".join("?" for _ in values)
    connection.execute(
      f"INSERT INTO podcasts VALUES ({placeholders})",
      values,
    )


def insert_podcast(
  path: Path,
  podcast_id: int,
  title: str,
  podcast_type: str,
  itunes_id: object = 123,
) -> None:
  with sqlite3.connect(path) as connection:
    row = list(connection.execute("SELECT * FROM podcasts LIMIT 1").fetchone())
    row[0] = podcast_id
    row[2] = title
    row[11] = podcast_type
    row[5] = itunes_id
    placeholders = ",".join("?" for _ in row)
    connection.execute(
      f"INSERT INTO podcasts VALUES ({placeholders})",
      row,
    )


@pytest.fixture
async def catalog(tmp_path: Path):
  create_database(tmp_path / DATABASE_NAME)

  def handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "feeds.example":
      return httpx.Response(
        200,
        content=(
          b"<rss><channel><item><title>Testing today</title>"
          b"<guid>episode-1</guid><description>Technology testing</description>"
          b"<pubDate>Thu, 16 Jul 2026 10:00:00 GMT</pubDate>"
          b"<enclosure url='https://example.test/episode.mp3' "
          b"type='audio/mpeg'/></item></channel></rss>"
        ),
      )
    return httpx.Response(404)

  client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
  settings = Settings(
    data_path=str(tmp_path),
    database_auto_update=False,
  )
  database = PodcastDatabase(settings, client)
  await database.start()
  yield settings, database, client
  await database.close()
  await client.aclose()


async def test_tool_schemas_remain_structured_and_constrained(catalog) -> None:
  settings, database, client = catalog
  tools = {
    tool.name: tool
    for tool in await create_mcp_server(
      settings,
      database,
      client,
    ).list_tools()
  }
  assert len(tools) == 10
  schema = tools["search_podcasts"].inputSchema["properties"]
  assert schema["query"]["minLength"] == 1
  assert schema["limit"]["minimum"] == 1
  assert schema["limit"]["maximum"] == 100
  assert (
    tools["search_podcasts"].outputSchema["properties"]["podcasts"]["type"]
    == "array"
  )
  episode_schema = tools["list_podcast_episodes"].outputSchema["$defs"][
    "EpisodeSummary"
  ]
  assert "feed_id" in episode_schema["required"]
  assert "feedId" not in episode_schema["properties"]
  assert "enclosure_url" in episode_schema["properties"]
  assert "enclosureUrl" not in episode_schema["properties"]


async def test_search_and_details_use_offline_database(catalog) -> None:
  settings, database, client = catalog
  server = create_mcp_server(settings, database, client)
  _, search = await server.call_tool(
    "search_podcasts",
    {
      "query": "testing",
      "language": "en",
      "category": "Technology",
      "limit": 5,
    },
  )
  _, details = await server.call_tool("get_podcast", {"feed_id": 42})
  assert search["count"] == 1
  assert search["podcasts"][0]["id"] == 42
  assert details["author"] == "Author"
  assert details["categories"][0]["name"] == "Technology"


async def test_noncanonical_snapshot_records_are_normalized_or_skipped(
  tmp_path: Path,
) -> None:
  path = tmp_path / DATABASE_NAME
  create_database(path)
  insert_podcast(path, 43, "Capitalized Type", "Episodic")
  insert_podcast(path, 44, "Unknown Type", "periodic")
  insert_podcast(path, 45, "", "episodic")
  client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: None))
  settings = Settings(
    data_path=str(tmp_path),
    database_auto_update=False,
  )
  database = PodcastDatabase(settings, client)
  await database.start()
  server = create_mcp_server(settings, database, client)
  _, result = await server.call_tool(
    "discover_podcasts",
    {"topic": "Type", "limit": 10},
  )
  podcasts = {item["title"]: item for item in result["podcasts"]}
  assert podcasts["Capitalized Type"]["podcast_type"] == "episodic"
  assert podcasts["Unknown Type"]["podcast_type"] is None
  assert "" not in podcasts
  await database.close()
  await client.aclose()


async def test_search_episodes_accepts_empty_itunes_id(
  tmp_path: Path,
) -> None:
  path = tmp_path / DATABASE_NAME
  create_database(path)
  insert_podcast(path, 43, "Empty iTunes", "episodic", "")

  def handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "feeds.example":
      return httpx.Response(
        200,
        content=(
          b"<rss><channel><item><title>Recent episode</title>"
          b"<guid>episode-empty-itunes</guid></item></channel></rss>"
        ),
      )
    return httpx.Response(404)

  client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
  settings = Settings(
    data_path=str(tmp_path),
    database_auto_update=False,
  )
  database = PodcastDatabase(settings, client)
  await database.start()
  server = create_mcp_server(settings, database, client)
  _, result = await server.call_tool(
    "search_episodes",
    {"query": "Empty iTunes", "limit": 10},
  )
  assert result == {"episodes": [], "count": 0}
  _, details = await server.call_tool("get_podcast", {"feed_id": 43})
  assert details["itunes_id"] is None
  await database.close()
  await client.aclose()


async def test_persistent_search_indexes_are_built(catalog) -> None:
  _, database, _ = catalog
  rows = await database.rows(
    "SELECT name FROM sqlite_master WHERE "
    "name IN ('podcasts_fts', 'kansa_rank_idx') ORDER BY name"
  )
  assert [row["name"] for row in rows] == [
    "kansa_rank_idx",
    "podcasts_fts",
  ]


async def test_identical_queries_are_served_from_memory(
  catalog,
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  _, database, _ = catalog
  original = database._rows
  calls = 0

  def counted(sql: str, parameters: tuple) -> list[dict]:
    nonlocal calls
    calls += 1
    return original(sql, parameters)

  monkeypatch.setattr(database, "_rows", counted)
  first = await database.rows(
    "SELECT title FROM podcasts WHERE id = ?",
    (42,),
  )
  first[0]["title"] = "changed by caller"
  second = await database.rows(
    "SELECT title FROM podcasts WHERE id = ?",
    (42,),
  )
  assert calls == 1
  assert second[0]["title"] == "Example Podcast"


async def test_episode_listing_fetches_rss_and_populates_cache(catalog) -> None:
  settings, database, client = catalog
  server = create_mcp_server(settings, database, client)
  _, listed = await server.call_tool(
    "list_podcast_episodes",
    {"feed_id": 42, "limit": 5},
  )
  episode_id = listed["episodes"][0]["id"]
  _, episode = await server.call_tool(
    "get_episode",
    {"episode_id": episode_id},
  )
  assert episode["title"] == "Testing today"
  assert episode["enclosure_url"].endswith("episode.mp3")


async def test_categories_use_stable_local_identifiers(catalog) -> None:
  settings, database, client = catalog
  server = create_mcp_server(settings, database, client)
  _, result = await server.call_tool("list_categories", {})
  assert result == {
    "categories": [
      {"id": _category_id("News"), "name": "News"},
      {"id": _category_id("Technology"), "name": "Technology"},
    ],
    "count": 2,
  }


async def test_invalid_inputs_are_rejected_without_queries(catalog) -> None:
  settings, database, client = catalog
  server = create_mcp_server(settings, database, client)
  with pytest.raises(Exception, match="validation error"):
    await server.call_tool(
      "search_podcasts",
      {"query": "", "limit": 101},
    )


async def test_missing_cached_episode_is_a_safe_error(catalog) -> None:
  settings, database, client = catalog
  server = create_mcp_server(settings, database, client)
  with pytest.raises(ToolError, match="list or search episodes first"):
    await server.call_tool("get_episode", {"episode_id": 123})


async def test_legacy_episode_cache_schema_is_migrated(
  tmp_path: Path,
) -> None:
  create_database(tmp_path / DATABASE_NAME)
  cache_path = tmp_path / "episodes_cache.db"
  payload = '{"id":123,"feed_id":42,"title":"Cached","feed_title":null}'

  with sqlite3.connect(cache_path) as connection:
    connection.execute(
      "CREATE TABLE episodes (id TEXT PRIMARY KEY, "
      "feed_id TEXT NOT NULL, payload TEXT NOT NULL)"
    )
    connection.execute(
      "INSERT INTO episodes VALUES (?, ?, ?)",
      ("123", "42", payload),
    )

  client = httpx.AsyncClient(
    transport=httpx.MockTransport(lambda _: httpx.Response(404))
  )
  settings = Settings(
    data_path=str(tmp_path),
    database_auto_update=False,
  )
  database = PodcastDatabase(settings, client)
  await database.start()

  with sqlite3.connect(cache_path) as connection:
    columns = [
      column[1] for column in connection.execute("PRAGMA table_info(episodes)")
    ]

  assert columns == ["id", "payload"]
  assert (await database.cached_episode(123))["title"] == "Cached"
  await database.close()
  await client.aclose()


async def test_database_download_is_validated_and_installed(
  tmp_path: Path,
) -> None:
  source = tmp_path / "source.db"
  create_database(source)
  archive = io.BytesIO()
  with tarfile.open(fileobj=archive, mode="w:gz") as bundle:
    bundle.add(source, arcname=DATABASE_NAME)

  client = httpx.AsyncClient(
    transport=httpx.MockTransport(
      lambda _: httpx.Response(200, content=archive.getvalue())
    )
  )
  data_path = tmp_path / "data"
  settings = Settings(
    data_path=str(data_path),
    database_auto_update=False,
  )
  database = PodcastDatabase(settings, client)
  await database.start()
  assert (data_path / DATABASE_NAME).is_file()
  assert (await database.rows("SELECT title FROM podcasts"))[0][
    "title"
  ] == "Example Podcast"
  await client.aclose()


def test_offline_settings_load_from_environment(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  monkeypatch.setenv("OREMI_KANSA_DATA_PATH", "/tmp/catalog")
  monkeypatch.setenv("OREMI_KANSA_DATABASE_AUTO_UPDATE", "false")
  monkeypatch.setenv("OREMI_KANSA_DATABASE_UPDATE_INTERVAL_HOURS", "12")
  settings = Settings()
  assert settings.data_path == "/tmp/catalog"
  assert settings.database_auto_update is False
  assert settings.database_update_interval_hours == 12
