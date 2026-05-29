from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class Author(APIModel):
    id: str = ""
    name: str = ""
    avatar: str = ""


class Image(APIModel):
    url: str = ""
    width: int = 0
    height: int = 0
    live_photo: bool = Field(False, alias="livePhoto")


class Video(APIModel):
    url: str = ""
    poster: str = ""
    width: int = 0
    height: int = 0
    duration: int = 0
    format: str = ""
    codec: str = ""


class Stats(APIModel):
    likes: str = ""
    collects: str = ""
    comments: str = ""
    shares: str = ""


class Collection(APIModel):
    id: str = ""
    platform: str = ""
    source_id: str = Field("", alias="sourceId")
    source_url: str = Field("", alias="sourceUrl")
    canonical_url: str = Field("", alias="canonicalUrl")
    type: Literal["normal", "video"] | str = "normal"
    title: str = ""
    content: str = ""
    author: Author = Field(default_factory=Author)
    images: list[Image] = Field(default_factory=list)
    video: Video | None = None
    tags: list[str] = Field(default_factory=list)
    stats: Stats = Field(default_factory=Stats)
    source_created_at: str = Field("", alias="sourceCreatedAt")
    source_updated_at: str = Field("", alias="sourceUpdatedAt")
    created_at: str = Field("", alias="createdAt")
    updated_at: str = Field("", alias="updatedAt")
    collected_at: str = Field("", alias="collectedAt")
    deleted_at: str = Field("", alias="deletedAt")


class DataFile(APIModel):
    schema_version: int = Field(1, alias="schemaVersion")
    revision: int = 0
    updated_at: str = Field("", alias="updatedAt")
    collections: list[Collection] = Field(default_factory=list)


class CollectionPatch(APIModel):
    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    source_url: str | None = Field(None, alias="sourceUrl")


def model_to_api(value: BaseModel) -> dict:
    return value.model_dump(by_alias=True, exclude_none=True)
