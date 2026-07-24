**Oremi Kànsà** is an MCP server for discovering podcasts through the
Podcast Index. It provides AI assistants and autonomous agents with a
standardized interface to search, browse, and retrieve podcast information
using the Model Context Protocol (MCP).

Designed to run in Docker, Oremi Kànsà exposes tools for searching podcasts,
exploring episodes, browsing categories, and retrieving metadata from
Podcast Index. It enables MCP-compatible clients to access podcast content
without interacting directly with the Podcast Index API.

The name **Oremi Kànsà** comes from the Yoruba language. _Oremi_ means
_"my friend"_, reflecting the project's goal of building a helpful and
trustworthy AI ecosystem. _Kànsà_ is derived from the Yoruba word associated
with _broadcasting_ or _broadcast media_, representing the service's
responsibility for helping AI agents discover podcast content through a
unified MCP interface.

Project repository: https://gitlab.com/demsking/oremi-kansa

![Oremi Isinmi Logo](./static/logo.jpg)

## Core Capabilities

- Search and discover podcasts by topic, language, and category
- Retrieve detailed podcast and episode metadata
- Browse categories, trending shows, and related podcasts
- Return structured, validated response models for MCP clients
- Use either the public Podcast Index API or the offline SQLite catalog
- Accelerate searches with persistent FTS5 indexes and a bounded memory cache
- Persist and periodically refresh the catalog in `/oremi/data` in Docker
- Configure database updates, HTTP timeouts, HTTP binding, API prefix, and
  logging through environment variables
- Serve MCP over Streamable HTTP
- Run as a lightweight Docker container with simple deployment.
- Integrate seamlessly with the Oremi ecosystem and other MCP-compatible
  clients.

## Deployment

Oremi Kànsà is distributed as a multi-platform Docker image for
`linux/amd64` and `linux/arm64`. It can be deployed as a standalone service or
integrated into the Oremi ecosystem alongside services such as Oremi Isinmi,
Oremi Ojọ, Oremi Kànsà, and Oremi Kansa.

The following sections describe the available Docker image, persistent storage
requirements, and example deployments using both Docker and Docker Compose.

### Command Line

Before installing Oremi Kànsà from PyPI, ensure the following requirements are
met:

- Python 3.12 or later.
- `uv` (recommended) or `pip` for package installation.

Oremi Kànsà can be installed either as a standalone command-line application
or as a Python package.

#### Install with uv

```sh
uv tool install oremi-kansa
```

#### Install with pip

```sh
python -m pip install oremi-kansa
```

#### Usage

```text
oremi-kansa [-h] [-v]
```

When started without arguments, Oremi Kànsà launches the HTTP server using the
configured environment variables.

#### Options

- `-h`, `--help`: Display the command-line help and exit.
- `-v`, `--version`: Display the installed version and exit.

### Docker Image

The [`demsking/oremi-kansa`](https://hub.docker.com/r/demsking/oremi-kansa)
Docker image is officially available on Docker Hub, supporting both
`linux/amd64` and `linux/arm64` platforms. The image exposes port `5046`, which
serves the REST API and the interactive documentation.

The interactive documentation can be accessed at `http://localhost:5046/docs`
and allows testing available endpoints directly from the browser.

### Volumes

Oremi Kànsà stores its offline catalog and episode cache in `/oremi/data`.
Mount persistent storage because the catalog is several gigabytes after
extraction and is retained across container recreation.

Oremi Kànsà is designed for Docker Swarm deployments with multiple replicas
sharing the same `/oremi/data` volume. Replicas coordinate catalog replacement
and persistent search-index creation with a filesystem lock in that directory,
use unique staging files for downloads, and invalidate each process memory
cache when another replica replaces the catalog. The shared volume must support
POSIX file locking; use a Swarm-compatible volume driver that can be mounted by
all nodes running the service.

NFS is a suitable option when every cluster node that may run a replica mounts
the same export and the server/client configuration supports POSIX locks.
Prefer NFSv4, keep locking enabled, and avoid `nolock` mounts. Because Oremi
Kànsà stores SQLite files on this volume, the NFS server should provide stable
locking and close-to-open cache consistency across all nodes.

### System Requirements

Oremi Kànsà is lightweight once the catalog is ready, but the first startup and
each catalog refresh can be resource intensive because the service downloads,
validates, extracts, and indexes a multi-gigabyte SQLite database.

These requirements apply to the default `database` backend. The `api` backend
does not download or index the local catalog, so it starts much faster and only
needs enough storage for the small episode cache.

- **Minimum per replica**: 1 CPU, 2 GB RAM, and 20 GB of shared persistent
  storage for `/oremi/data`.
- **Recommended per replica**: 2 CPUs, 4 GB RAM, and 30 GB or more of shared
  persistent storage backed by SSD or low-latency NFS.
- **Storage**: Use a shared volume with POSIX locking for clustered
  deployments. NFSv4 is recommended when using NFS.
- **Startup time**: On slow CPUs, low-memory hosts, HDD-backed storage, or
  slower NFS exports, validation and search-index creation can take much longer.
  Increase the Docker health-check start period if your environment needs more
  than the image default.

### Deploy with Docker

Use the official Docker image
[`demsking/oremi-kansa`](https://hub.docker.com/r/demsking/oremi-kansa)
to run Oremi Kànsà:

```sh
docker run -d \
  --name oremi-kansa \
  --env-file <path_to_env_file> \
  -v oremi-kansa-data:/oremi/data \
  -p 5046:5046 \
  demsking/oremi-kansa
```

Replace `<path_to_env_file>` with the path to your
[environment variables](#description/configuration) file containing the desired
configuration.

### Deploy with Docker Compose

Create a `compose.yaml` file:

```yaml
services:
  kansa:
    image: demsking/oremi-kansa
    restart: unless-stopped
    ports:
      - "5046:5046"
    volumes:
      - kansa-data:/oremi/data

volumes:
  kansa-data:
```

Start the services with:

```sh
docker compose up -d
```

Once started, open the interactive documentation at:

```txt
http://localhost:5046/docs/
```

### Deploy with Docker Swarm

For production Swarm deployments, run at least two replicas behind the Swarm
routing mesh or an external reverse proxy. Every replica must mount the same
shared volume at `/oremi/data`:

```yaml
services:
  kansa:
    image: demsking/oremi-kansa
    ports:
      - "5046:5046"
    volumes:
      - kansa-data:/oremi/data
    deploy:
      replicas: 2
      restart_policy:
        condition: on-failure
      resources:
        reservations:
          cpus: "1.0"
          memory: 2G
        limits:
          cpus: "2.0"
          memory: 4G

volumes:
  kansa-data:
    driver: <shared-volume-driver>
```

Replace `<shared-volume-driver>` with the storage driver used by your cluster.
For an NFS-backed deployment, configure the driver or plugin to mount the same
NFS export on every cluster node that may run a replica, for example an export
dedicated to `/oremi/data`. Do not give each replica its own local `/oremi/data`
volume unless you intentionally want each replica to download, index, and cache
an independent catalog. The `deploy.resources` values above are conservative
defaults; increase them for low-performance nodes or very slow shared storage.

## Configuration

Every setting is optional and uses the `OREMI_KANSA_` prefix.

### Server Settings

- **`OREMI_KANSA_SERVER_HOST`**
  HTTP address on which the server listens. Use `0.0.0.0` in a
  container or when accepting connections from other machines.
  Defaults to `0.0.0.0`.

- **`OREMI_KANSA_SERVER_PORT`**
  HTTP listening port. Must be between `1` and `65535`.
  Defaults to `5046`.

- **`OREMI_KANSA_API_PREFIX`**
  Base path for every HTTP endpoint. Useful when exposing
  below a path like `/kansa` via reverse proxy. Must begin with
  `/`; trailing slash removed automatically. Defaults to `/`.

### Catalog Backend

Choose between local database or direct Podcast Index API:

- **`OREMI_KANSA_CATALOG_BACKEND`**
  Backend mode: `database` (local SQLite) or `api` (direct
  Podcast Index API). Defaults to `database`.

- **`OREMI_KANSA_PODCAST_INDEX_API_BASE_URL`**
  Podcast Index API base URL. Used only in `api` mode.
  Defaults to `https://api.podcastindex.org/api/1.0`.

- **`OREMI_KANSA_PODCAST_INDEX_API_KEY`**
  Podcast Index API key. Required in `api` mode.

- **`OREMI_KANSA_PODCAST_INDEX_API_SECRET`**
  Podcast Index API secret. Required in `api` mode.
  Redacted from logs.

#### Backend Mode Comparison

- **`database` mode**
  Slower first startup; supports full-catalog searching after
  download and indexing.

- **`api` mode**
  Avoids multi-gigabyte download and indexing; requires
  Podcast Index API credentials; relies on public API for
  searches.

### Database Settings (database mode only)

- **`OREMI_KANSA_DATABASE_DOWNLOAD_URL`**
  Location of the compressed Podcast Index SQLite catalog.

- **`OREMI_KANSA_DATA_PATH`**
  Catalog and episode-cache directory. In Docker Swarm, point
  all replicas to the same mounted shared volume. Defaults to
  `data` locally and `/oremi/data` in Docker.

- **`OREMI_KANSA_DATABASE_AUTO_UPDATE`**
  Enable atomic background catalog updates. Defaults to `true`.

- **`OREMI_KANSA_DATABASE_UPDATE_INTERVAL_HOURS`**
  Hours between update attempts. Defaults to `24`.

- **`OREMI_KANSA_DATABASE_SEARCH_INDEX_ENABLED`**
  Build persistent FTS5, category, language, and ranking
  indexes. First startup takes longer; subsequent startups and
  queries reuse them. Defaults to `true`.

> **Performance note**: On low-performance storage, database
> validation and persistent search-index creation can take
> significant time as they scan and write a multi-gigabyte
> SQLite catalog.

### Query & Network Settings

- **`OREMI_KANSA_QUERY_CACHE_SIZE`**
  Maximum number of identical query results retained in
  memory. Set to `0` to disable. Cache clears when snapshot is
  replaced. Defaults to `256`.

- **`OREMI_KANSA_USER_AGENT`**
  Identifier used for catalog and RSS feed downloads.
  Defaults to `oremi-kansa/<version>`.

- **`OREMI_KANSA_HTTP_CONNECT_TIMEOUT`**
  Connection timeout in seconds. Defaults to `5`.

- **`OREMI_KANSA_HTTP_READ_TIMEOUT`**
  Response read timeout in seconds. Defaults to `15`.

- **`OREMI_KANSA_HTTP_WRITE_TIMEOUT`**
  Request write timeout in seconds. Defaults to `5`.

- **`OREMI_KANSA_HTTP_POOL_TIMEOUT`**
  Connection pool timeout in seconds. Defaults to `5`.

### Logging

- **`OREMI_KANSA_LOG_LEVEL`**
  Logging verbosity. Accepted values: `DEBUG`, `INFO`,
  `WARNING`, `ERROR`, `CRITICAL`. At `DEBUG`, logs include
  Python logger name. Defaults to `INFO`.

- **`OREMI_KANSA_LOG_FILE`**
  Optional path for persistent logs. When set, console
  logging remains enabled and parent directories are created
  automatically. Files rotate at approximately 5 MB, with up to
  five backups retained. Unset by default (console only).

## Model Context Protocol

Oremi Kànsà implements the Model Context Protocol (MCP) using a strongly-typed
server. It exposes its core functionality as a set of tools, resources and
prompts that LLM agents can call directly.

The MCP server uses the **Streamable HTTP transport** protocol and is mounted at:

```txt
/mcp
```

### Available MCP Tools

Tool inputs use constrained MCP schemas. Result limits must be between `1` and
`100`. Every result is a structured, validated Pydantic response model.

- `search_podcasts` searches by query, language, and category.
- `get_podcast` returns complete metadata for one feed ID.
- `list_podcast_episodes` returns a feed's newest episodes.
- `get_episode` returns an episode previously stored by a list or search call.
- `search_episodes` searches RSS entries from locally matched podcasts.
- `list_categories` lists the categories available for discovery.
- `browse_category` browses popular podcasts by category and language.
- `trending_podcasts` lists podcasts currently trending in a language.
- `similar_podcasts` finds shows related to a feed ID.
- `discover_podcasts` discovers shows by topic, language, category, and
  explicit-content preference.

Category IDs and episode IDs are stable identifiers generated locally from
category names and feed episode identities, respectively.

### Available MCP Resources

Resources expose direct, read-only data paths for catalog entities. Every
resource result is serialized to JSON (`application/json`).

- `podcasts:///{feed_id}/details` returns metadata for a specific podcast feed.
- `podcasts:///{feed_id}/episodes` returns the recent episodes for a podcast.
- `episodes:///{episode_id}/details` returns metadata for a cached episode.
- `categories:///list` returns the list of available categories.

### Available MCP Prompts

Prompts assist AI agents in orchestration and workflow execution:

- `podcast_discovery` recommends podcasts matching a topic, language, and
  category.
- `episode_search` helps agents retrieve relevant episodes across feeds.
- `category_explorer` helps agents explore categories and browse top podcasts.

## Development

See the [contribution guide](https://gitlab.com/demsking/oremi-kansa/-/blob/main/CONTRIBUTING.md)
for development environment and contribution guidance.

## Versioning

Oremi Kànsà project adheres to [Semantic Versioning](https://semver.org/)
(SemVer). Version numbers follow the `MAJOR.MINOR.PATCH` format:

- **MAJOR** version increments for incompatible API changes
- **MINOR** version increments for backward-compatible new functionality
- **PATCH** version increments for backward-compatible bug fixes

The current version can be found by running:

```bash
oremi-kansa --version
```

## License

Copyright 2023-2026 Sébastien Demanou. All Rights Reserved.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://gitlab.com/demsking/oremi-kansa/-/blob/main/LICENSE

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
