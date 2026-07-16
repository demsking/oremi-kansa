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
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator

NonEmptyString = Annotated[
  str,
  Field(min_length=1, max_length=500, description="Non-empty text."),
]

LanguageCode = Annotated[
  str,
  Field(
    min_length=2,
    max_length=6,
    pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z]{2})?$",
    description="ISO language code, such as en or pt-BR.",
  ),
]

ResultLimit = Annotated[
  int,
  Field(ge=1, le=100, description="Number of results, from 1 through 100."),
]

PositiveId = Annotated[
  int,
  Field(gt=0, description="Positive catalog identifier."),
]


class PodcastType(StrEnum):
  """Podcast publishing order."""

  EPISODIC = "episodic"
  SERIAL = "serial"


class PodcastMedium(StrEnum):
  """Podcast namespace medium."""

  PODCAST = "podcast"
  MUSIC = "music"
  VIDEO = "video"
  FILM = "film"
  AUDIOBOOK = "audiobook"
  NEWSLETTER = "newsletter"
  BLOG = "blog"
  PODCAST_LIST = "podcastL"
  MUSIC_LIST = "musicL"
  VIDEO_LIST = "videoL"
  FILM_LIST = "filmL"
  AUDIOBOOK_LIST = "audiobookL"
  NEWSLETTER_LIST = "newsletterL"
  BLOG_LIST = "blogL"
  MIXED = "mixed"


class ApiModel(BaseModel):
  """Base model for validated Podcast Index data."""

  model_config = ConfigDict(
    extra="ignore",
    populate_by_name=True,
    json_schema_mode_override="serialization",
  )


class PodcastCategory(ApiModel):
  """A Podcast Index category."""

  id: int = Field(description="Category identifier.")
  name: str = Field(min_length=1, description="Category name.")


class FundingInfo(ApiModel):
  """A podcast funding link."""

  url: str | None = None
  message: str | None = None


class ValueRecipient(ApiModel):
  """A recipient in a value-for-value split."""

  name: str | None = None
  type: str | None = None
  address: str | None = None
  split: int | None = None
  fee: bool | None = None
  custom_key: str | None = Field(
    default=None,
    validation_alias="customKey",
  )
  custom_value: str | None = Field(
    default=None,
    validation_alias="customValue",
  )


class ValueInfo(ApiModel):
  """Podcast value-for-value metadata."""

  model: str | None = None
  type: str | None = None
  method: str | None = None
  suggested: str | None = None
  recipients: list[ValueRecipient] = Field(
    default_factory=list,
    validation_alias="destinations",
  )


class PersonInfo(ApiModel):
  """A person credited on a podcast episode."""

  id: int | None = None
  name: str | None = None
  role: str | None = None
  group: str | None = None
  image: str | None = Field(default=None, validation_alias="img")
  href: str | None = None


class PodcastSummary(ApiModel):
  """Compact metadata for a podcast feed."""

  id: int = Field(gt=0, description="Podcast Index feed identifier.")
  title: str = Field(min_length=1, description="Podcast title.")
  url: str | None = Field(default=None, description="RSS feed URL.")
  link: str | None = Field(default=None, description="Podcast website URL.")
  description: str | None = Field(default=None)
  author: str | None = Field(default=None, alias="author")
  owner_name: str | None = Field(
    default=None,
    validation_alias="ownerName",
  )
  image: str | None = Field(default=None)
  artwork: str | None = Field(default=None)
  language: str | None = Field(default=None)
  explicit: bool | None = Field(default=None)
  podcast_type: PodcastType | None = Field(
    default=None,
    validation_alias="type",
  )
  medium: PodcastMedium | None = Field(default=None)
  episode_count: int | None = Field(
    default=None,
    validation_alias="episodeCount",
  )
  newest_item_publish_time: int | None = Field(
    default=None,
    validation_alias="newestItemPublishTime",
  )
  categories: list[PodcastCategory] = Field(default_factory=list)

  @field_validator("categories", mode="before")
  @classmethod
  def map_categories(cls, value: object) -> object:
    """Convert the API category mapping to category models."""
    if isinstance(value, dict):
      return [
        {"id": int(category_id), "name": name}
        for category_id, name in value.items()
      ]
    return value


class PodcastDetails(PodcastSummary):
  """Detailed metadata for a podcast feed."""

  guid: str | None = Field(default=None)
  itunes_id: int | None = Field(
    default=None,
    validation_alias="itunesId",
  )
  original_url: str | None = Field(
    default=None,
    validation_alias="originalUrl",
  )
  funding: list[FundingInfo] | None = Field(default=None)
  value: ValueInfo | None = Field(default=None)
  last_update_time: int | None = Field(
    default=None,
    validation_alias="lastUpdateTime",
  )


class EpisodeSummary(ApiModel):
  """Compact metadata for a podcast episode."""

  id: int = Field(gt=0, description="Stable local episode identifier.")
  title: str = Field(min_length=1, description="Episode title.")
  feed_id: int = Field(gt=0, validation_alias="feedId")
  feed_title: str | None = Field(
    default=None,
    validation_alias="feedTitle",
  )
  description: str | None = Field(default=None)
  link: str | None = Field(default=None)
  guid: str | None = Field(default=None)
  date_published: int | None = Field(
    default=None,
    validation_alias="datePublished",
  )
  duration: int | None = Field(default=None)
  enclosure_url: str | None = Field(
    default=None,
    validation_alias="enclosureUrl",
  )
  enclosure_type: str | None = Field(
    default=None,
    validation_alias="enclosureType",
  )
  image: str | None = Field(default=None)
  explicit: bool | None = Field(default=None)


class EpisodeDetails(EpisodeSummary):
  """Detailed metadata for one podcast episode."""

  transcript_url: str | None = Field(
    default=None,
    validation_alias="transcriptUrl",
  )
  chapters_url: str | None = Field(
    default=None,
    validation_alias="chaptersUrl",
  )
  season: int | None = Field(default=None)
  episode: int | None = Field(default=None)
  episode_type: str | None = Field(
    default=None,
    validation_alias="episodeType",
  )
  persons: list[PersonInfo] | None = Field(default=None)
  value: ValueInfo | None = Field(default=None)


class PodcastSearchResponse(ApiModel):
  """Results from a podcast keyword search."""

  podcasts: list[PodcastSummary]
  count: int = Field(ge=0)


class PodcastListResponse(ApiModel):
  """A validated list of podcasts."""

  podcasts: list[PodcastSummary]
  count: int = Field(ge=0)


class EpisodeSearchResponse(ApiModel):
  """Results from an episode keyword search."""

  episodes: list[EpisodeSummary]
  count: int = Field(ge=0)


class EpisodeListResponse(ApiModel):
  """A validated list of podcast episodes."""

  episodes: list[EpisodeSummary]
  count: int = Field(ge=0)


class CategoryListResponse(ApiModel):
  """All Podcast Index categories."""

  categories: list[PodcastCategory]
  count: int = Field(ge=0)


class ErrorDetails(ApiModel):
  """Safe details for a failed operation."""

  code: str = Field(min_length=1)
  message: str = Field(min_length=1)
