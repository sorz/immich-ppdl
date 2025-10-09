import logging
from enum import Enum
from os import environ
from pathlib import Path
from datetime import datetime, timedelta
from typing import Iterator
from uuid import UUID
from queue import Queue
from threading import Thread
from hashlib import sha1
import base64

from requests import Session
from requests.adapters import HTTPAdapter
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("immmich-ppdl")
session = Session()


class Settings(BaseSettings, cli_parse_args=True):
    immich_api_url: str = Field(..., description="e.g. https://myserver/api")
    immich_api_key: str = Field(
        ..., description="Required permission: asset.read, asset.download"
    )
    person_id: UUID = Field(..., description="Person UUID")
    _after: datetime | None = None
    after: datetime | None = Field(None, description="Photos created after that time")
    last_days: int | None = Field(
        None, description="Equivalent to --after (today - last_days)"
    )
    save_to: Path = Field(Path("."), description="Default to current directory")
    threads: int = Field(4, description="Number of downloading threads")
    dry: bool = Field(False, description="List photos without actually download")

    model_config = SettingsConfigDict()

    @model_validator(mode="after")
    def parse(self) -> "Settings":
        if self.after is not None and self.last_days is not None:
            raise ValueError("`after` and `last_days` cannot both be set")
        if self.after is not None:
            self._after = self.after
        elif self.last_days is not None:
            self._after = datetime.today() - timedelta(days=self.last_days)
        return self


class AssetVisibility(Enum):
    ARCHIVE = "archive"
    TIMELINE = "timeline"
    HIDDEN = "hidden"
    LOCKED = "locked"


class AssetType(Enum):
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    AUDIO = "AUDIO"
    OTHER = "OTHER"


class SearchAssetsRequest(BaseModel):
    personIds: list[UUID] | None = None
    visibility: AssetVisibility | None = None
    type: AssetType | None = None
    createdAfter: datetime | None = None
    size: int = Field(..., description="page size")
    page: int = Field(..., description="start from 1")


class Asset(BaseModel):
    id: str
    checksum: str = Field(..., description="base64 encoded sha1 hash")
    createdAt: datetime = Field(
        ..., description="UTC timestamp when it was originally uploaded to Immich"
    )
    fileCreatedAt: datetime = Field(
        ..., description="actual UTC timestamp for chronological sorting"
    )
    localDateTime: datetime = Field(
        ..., description="local date and time when the photo/video was taken"
    )
    originalFileName: str
    originalPath: str


class SearchAssetResponse(BaseModel):
    class AssetResponse(BaseModel):
        items: list[Asset]
        nextPage: str | None

    assets: AssetResponse


def search_assets(settings: Settings) -> Iterator[Asset]:
    page: int | None = 1
    while page:
        req = SearchAssetsRequest(
            personIds=[settings.person_id],
            visibility=AssetVisibility.TIMELINE,
            type=AssetType.IMAGE,
            createdAfter=settings._after,
            size=50,
            page=page,
        )
        resp = session.post(
            f"{settings.immich_api_url}/search/metadata",
            json=req.model_dump(mode="json", exclude_none=True),
        )
        resp.raise_for_status()
        asset_resp = SearchAssetResponse.model_validate(resp.json())
        page = int(asset_resp.assets.nextPage) if asset_resp.assets.nextPage else None
        yield from asset_resp.assets.items


def download_and_sha1(url: str, to: Path) -> bytes:
    logger.debug(f"Downalod {url} to {to}")
    hasher = sha1()
    with session.get(url, stream=True) as resp:
        resp.raise_for_status()
        with to.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=None):
                hasher.update(chunk)
                f.write(chunk)
    return hasher.digest()


def fetch_asset(settings: Settings, asset: Asset, path: Path):
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    url = f"{settings.immich_api_url}/assets/{asset.id}/original"
    file_hash = download_and_sha1(url, path)
    path_hash = sha1(f"path:{asset.originalPath}".encode()).digest()
    # Immich use hash of path for files in external libraries
    if base64.decodebytes(asset.checksum.encode()) not in (file_hash, path_hash):
        raise Exception("hash mismatched")


def fetch_assets(thread_id: int, settings: Settings, queue: Queue[Asset | None]):
    logger.debug(f"Th#{thread_id} started")
    while True:
        asset = queue.get()
        if asset is None:
            logger.debug(f"Th#{thread_id} done")
            break
        # Save to /YYYY/MM/DD/originalFileName
        date = asset.localDateTime
        path = (
            settings.save_to
            / f"{date.year}"
            / f"{date.month:02d}"
            / f"{date.day:02d}"
            / asset.originalFileName
        )
        if path.exists():
            logger.debug(f"Th#{thread_id} skip existing {path}")
            continue
        if settings.dry:
            print(path)
            continue
        try:
            fetch_asset(settings, asset, path)
        except Exception as err:
            logger.error(
                f"Th#{thread_id} failed to download {path} ({asset.id}): {err}"
            )
            path.unlink(missing_ok=True)
            continue
        logger.info(f"Th#{thread_id} save to {path}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s\t%(message)s")
    settings = Settings(
        _secrets_dir=environ.get("CREDENTIALS_DIRECTORY"),  # type: ignore
    )
    logger.info(f"Download person {settings.person_id} to {settings.save_to.resolve()}")
    if settings.dry:
        logger.warning("Dry mode enabled, won't download any files")
    session.headers["x-api-key"] = settings.immich_api_key
    session.mount(
        settings.immich_api_url,
        HTTPAdapter(
            pool_connections=settings.threads + 1,
            pool_maxsize=settings.threads + 1,
            max_retries=3,
        ),
    )

    # Setup threads
    queue: Queue[Asset | None] = Queue(maxsize=settings.threads)
    threads: list[Thread] = []
    for i in range(settings.threads):
        thread = Thread(
            target=fetch_assets,
            name=f"fetch-{i}",
            args=(i, settings, queue),
            daemon=True,
        )
        thread.start()
        threads.append(thread)
    # Feed assets
    for asset in search_assets(settings):
        queue.put(asset)
    for _ in threads:
        queue.put(None)
    # Wait all to done
    for thread in threads:
        thread.join()
    logger.info("All done")


if __name__ == "__main__":
    main()
