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
- Query the offline Podcast Index SQLite catalog with structured models
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

## Configuration

Every setting is optional and uses the `OREMI_KANSA_` prefix.

### Server

- **`OREMI_KANSA_SERVER_HOST`** — HTTP address on which the server listens.
  Defaults to `127.0.0.1`. Use `0.0.0.0` in a container or when the service must
  accept connections from other machines.

- **`OREMI_KANSA_SERVER_PORT`** — HTTP listening port. Defaults to `5046` and
  must be between `1` and `65535`.

- **`OREMI_KANSA_API_PREFIX`** — Base path for every HTTP endpoint. Defaults
  to `/`. This is useful when Oremi Kànsà is exposed below a path such as
  `/kansa` by a reverse proxy. The value must begin with `/`; a trailing slash
  is removed automatically.

### Offline Podcast Index database

- **`OREMI_KANSA_DATABASE_DOWNLOAD_URL`** — Location of the compressed
  Podcast Index SQLite catalog.

- **`OREMI_KANSA_DATA_PATH`** — Catalog and episode-cache directory. Defaults
  to `data` locally and `/oremi/data` in Docker.

- **`OREMI_KANSA_DATABASE_AUTO_UPDATE`** — Enables atomic background catalog
  updates. Defaults to `true`.

- **`OREMI_KANSA_DATABASE_UPDATE_INTERVAL_HOURS`** — Hours between update
  attempts. Defaults to `24`.

- **`OREMI_KANSA_DATABASE_SEARCH_INDEX_ENABLED`** — Builds persistent FTS5,
  category, language, and ranking indexes. Defaults to `true`. The first
  startup for a new snapshot takes longer while these indexes are built;
  subsequent queries and startups reuse them.

- **`OREMI_KANSA_QUERY_CACHE_SIZE`** — Maximum number of identical query
  results retained in process memory. Defaults to `256`. Set it to `0` to
  disable the memory cache. The cache is cleared whenever the snapshot is
  replaced.

- **`OREMI_KANSA_USER_AGENT`** — Identifier used for catalog and RSS feed
  downloads. Defaults to `oremi-kansa/<version>`.

- **`OREMI_KANSA_HTTP_CONNECT_TIMEOUT`** — Connection timeout in seconds.
  Defaults to `5`.

- **`OREMI_KANSA_HTTP_READ_TIMEOUT`** — Response read timeout in seconds.
  Defaults to `15`.

- **`OREMI_KANSA_HTTP_WRITE_TIMEOUT`** — Request write timeout in seconds.
  Defaults to `5`.

- **`OREMI_KANSA_HTTP_POOL_TIMEOUT`** — Connection pool timeout in seconds.
  Defaults to `5`.

### Logging

- **`OREMI_KANSA_LOG_LEVEL`** — Application logging verbosity. Defaults to
  `INFO`. Accepted values are `DEBUG`, `INFO`, `WARNING`, `ERROR`, and
  `CRITICAL`. At `DEBUG`, log records also include the Python logger name.

- **`OREMI_KANSA_LOG_FILE`** — Optional path for persistent logs. It is unset
  by default, so logs are written only to the console. When configured, console
  logging remains enabled and parent directories are created automatically.
  Files rotate at approximately 5 MB, with up to five backups retained.

Oremi Kànsà logs the effective configuration during startup.

## Transport

Oremi Kànsà uses MCP Streamable HTTP. With the default configuration, connect
an MCP client to:

```text
http://127.0.0.1:5046/mcp
```

The health endpoint is `/health/`, and this documentation is served at `/docs/`.
If `OREMI_KANSA_API_PREFIX` is set, prepend that path to all three endpoints.

## Tools

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

## Development

See the [contribution guide](https://gitlab.com/demsking/oremi-kansa/-/blob/main/CONTRIBUTING.md)
for development environment and contribution guidance.

## Versioning

Oremi Kànsà follows [Semantic Versioning](https://semver.org/). Display the
installed version with:

```bash
oremi-kansa --version
```

## License

Copyright 2026 Sébastien Demanou. All Rights Reserved.

Licensed under the Apache License, Version 2.0. See the
[LICENSE](https://gitlab.com/demsking/oremi-kansa/-/blob/main/LICENSE) for the
complete license text.
