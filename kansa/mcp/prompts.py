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
from typing import Annotated

from mcp.server import MCPServer
from mcp.types import PromptMessage
from mcp.types import TextContent
from pydantic import Field


def register_mcp_prompts(mcp: MCPServer) -> None:
  @mcp.prompt()
  def podcast_discovery(
    topic: Annotated[
      str,
      Field(description=("The main topic, keyword, or theme of interest (e.g., science, technology, history).")),
    ],
    language: Annotated[
      str | None,
      Field(description="Optional language code to filter podcasts (e.g., en, fr)."),
    ] = None,
    category: Annotated[
      str | None,
      Field(description=("Optional category name to focus on (e.g., Technology, News, Education).")),
    ] = None,
  ) -> list[PromptMessage]:
    """Assist the user in discovering popular/trending podcasts."""
    topic_str = f"Topic: {topic}"
    lang_str = f", Language: {language}" if language else ""
    cat_str = f", Category: {category}" if category else ""
    return [
      PromptMessage(
        role="user",
        content=TextContent(
          type="text",
          text=(
            "The user wants to discover podcasts matching the following "
            f"criteria: {topic_str}{lang_str}{cat_str}.\n\n"
            "Please follow these steps to fulfill this request:\n"
            "1. Use `discover_podcasts` or `search_podcasts` with the topic, "
            "language, and category name to find relevant podcasts.\n"
            "2. If a specific category name is provided but category-based "
            "search needs a category ID, check if you need to call "
            "`list_categories` first to map the category name to a "
            "category ID.\n"
            "3. Using the IDs of the top matching podcasts, call `get_podcast` "
            "to retrieve their detailed metadata.\n"
            "4. Call `list_podcast_episodes` for the most promising podcasts to "
            "get a list of recent episodes.\n"
            "5. Present a curated list of recommendations to the user, including "
            "details such as titles, descriptions, categories, and recent "
            "episodes, formatted in a beautiful, readable list."
          ),
        ),
      )
    ]

  @mcp.prompt()
  def episode_search(
    query: Annotated[
      str,
      Field(
        description=("The topic, keyword, or phrase to search in podcast episodes (e.g., climate change, space exploration).")
      ),
    ],
    language: Annotated[
      str | None,
      Field(description=("Optional language code to filter the search (e.g., en, fr).")),
    ] = None,
  ) -> list[PromptMessage]:
    """Assist the user in searching and retrieving relevant episodes."""
    lang_str = f" in language '{language}'" if language else ""
    return [
      PromptMessage(
        role="user",
        content=TextContent(
          type="text",
          text=(
            f"The user wants to search for podcast episodes related to: '{query}'"
            f"{lang_str}.\n\n"
            "Please follow these steps:\n"
            "1. Call `search_episodes` with the query and optional language to "
            "find matching episodes.\n"
            "2. For the most relevant episodes returned, call `get_episode` "
            "using their episode IDs to retrieve detailed metadata and cached "
            "information.\n"
            "3. If needed, find the parent podcast details using `get_podcast` "
            "with the episode's feed ID.\n"
            "4. Compile a list of the matches, showing episode titles, release "
            "dates, descriptions, parent podcast names, and direct audio "
            "enclosure URLs."
          ),
        ),
      )
    ]

  @mcp.prompt()
  def category_explorer(
    category: Annotated[
      str | None,
      Field(description=("Optional category name to browse. If not specified, all categories will be listed first.")),
    ] = None,
    language: Annotated[
      str | None,
      Field(description=("Optional language code to filter podcasts in the category (e.g., en, fr).")),
    ] = None,
  ) -> list[PromptMessage]:
    """Assist the user in exploring podcast categories."""
    cat_str = f"'{category}'" if category else "all available categories"
    lang_str = f" filtered by language '{language}'" if language else ""
    return [
      PromptMessage(
        role="user",
        content=TextContent(
          type="text",
          text=(
            "The user wants to explore podcast categories: browsing "
            f"{cat_str}{lang_str}.\n\n"
            "Please follow these steps:\n"
            "1. If no category name is specified, call `list_categories` to list "
            "all available categories, then show them to the user and ask which "
            "one they want to explore.\n"
            "2. If a category name is specified, search for it in the list of "
            "categories (call `list_categories` first to find its ID).\n"
            "3. Use `browse_category` or `trending_podcasts` with the category "
            "ID and optional language to retrieve popular podcasts in that "
            "category.\n"
            "4. Retrieve detailed metadata for the top podcasts using "
            "`get_podcast`.\n"
            "5. Present a summary of the category and recommend the top "
            "podcasts in that category to the user."
          ),
        ),
      )
    ]
