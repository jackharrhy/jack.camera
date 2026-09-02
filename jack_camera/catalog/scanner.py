from __future__ import annotations

import mimetypes
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Literal

from PIL import Image, ImageOps

from jack_camera.catalog.database import (
    catalog_stats,
    connect_database,
    existing_file_fingerprints,
    finish_generation,
    initialize_database,
    next_generation,
)
from jack_camera.config import CatalogSettings

PREVIEW_REVISION = 1
PREVIEW_MAX_SIZE = 512
IGNORED_DIRECTORY = "@eaDir"


class CatalogScanError(RuntimeError):
    pass


@dataclass(frozen=True)
class Preview:
    state: Literal["ready", "unsupported", "error"]
    width: int | None = None
    height: int | None = None
    content: bytes | None = None
    media_type: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class ScanProgress:
    current: int
    total: int
    source_path: str


@dataclass(frozen=True)
class ScanSummary:
    folder_count: int
    file_count: int
    total_bytes: int
    preview_count: int
    error_count: int
    generated_previews: int
    reused_files: int


ProgressCallback = Callable[[ScanProgress], None]


def parse_capture_date(date_label: str) -> str | None:
    try:
        return date.fromisoformat(date_label.replace("_", "-")).isoformat()
    except ValueError:
        return None


def discover_edit_folders(photo_root: Path) -> list[Path]:
    if not photo_root.is_dir():
        raise CatalogScanError(f"photo root is not a directory: {photo_root}")

    folders = sorted(
        date_directory / "edits"
        for camera_directory in photo_root.iterdir()
        if camera_directory.is_dir() and camera_directory.name != IGNORED_DIRECTORY
        for date_directory in camera_directory.iterdir()
        if date_directory.is_dir() and date_directory.name != IGNORED_DIRECTORY
        if (date_directory / "edits").is_dir()
    )
    if not folders:
        raise CatalogScanError(
            f"no edits folders found below {photo_root}; refusing to empty the catalog"
        )
    return folders


def iter_folder_files(edit_folder: Path) -> Iterator[Path]:
    for path in sorted(edit_folder.rglob("*")):
        relative_path = path.relative_to(edit_folder)
        if IGNORED_DIRECTORY in relative_path.parts:
            continue
        if path.is_file() and not path.is_symlink():
            yield path


def create_preview(path: Path, media_type: str) -> Preview:
    if not media_type.startswith("image/"):
        return Preview(state="unsupported")

    try:
        with Image.open(path) as source:
            oriented = ImageOps.exif_transpose(source)
            width, height = oriented.size
            oriented.thumbnail(
                (PREVIEW_MAX_SIZE, PREVIEW_MAX_SIZE), Image.Resampling.LANCZOS
            )

            if "A" in oriented.getbands():
                background = Image.new("RGB", oriented.size, "white")
                background.paste(oriented, mask=oriented.getchannel("A"))
                thumbnail = background
            else:
                thumbnail = oriented.convert("RGB")

            output = BytesIO()
            thumbnail.save(output, "JPEG", quality=82, optimize=True)
            return Preview(
                state="ready",
                width=width,
                height=height,
                content=output.getvalue(),
                media_type="image/jpeg",
            )
    except (OSError, ValueError) as error:
        return Preview(
            state="error",
            error=f"{type(error).__name__}: {error}",
        )


def upsert_folder(
    connection: sqlite3.Connection,
    *,
    source_path: str,
    camera: str,
    date_label: str,
    generation: int,
) -> int:
    row = connection.execute(
        """
        INSERT INTO edit_folders (
            source_path,
            camera,
            date_label,
            capture_date,
            seen_generation
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source_path) DO UPDATE SET
            camera = excluded.camera,
            date_label = excluded.date_label,
            capture_date = excluded.capture_date,
            seen_generation = excluded.seen_generation
        RETURNING id
        """,
        (
            source_path,
            camera,
            date_label,
            parse_capture_date(date_label),
            generation,
        ),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def upsert_file(
    connection: sqlite3.Connection,
    *,
    folder_id: int,
    relative_path: str,
    path: Path,
    size_bytes: int,
    mtime_ns: int,
    media_type: str,
    preview: Preview,
    generation: int,
) -> None:
    connection.execute(
        """
        INSERT INTO media_files (
            folder_id,
            relative_path,
            filename,
            extension,
            media_type,
            size_bytes,
            mtime_ns,
            width,
            height,
            preview_state,
            thumbnail,
            thumbnail_mime,
            preview_error,
            preview_revision,
            seen_generation
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(folder_id, relative_path) DO UPDATE SET
            filename = excluded.filename,
            extension = excluded.extension,
            media_type = excluded.media_type,
            size_bytes = excluded.size_bytes,
            mtime_ns = excluded.mtime_ns,
            width = excluded.width,
            height = excluded.height,
            preview_state = excluded.preview_state,
            thumbnail = excluded.thumbnail,
            thumbnail_mime = excluded.thumbnail_mime,
            preview_error = excluded.preview_error,
            preview_revision = excluded.preview_revision,
            seen_generation = excluded.seen_generation
        """,
        (
            folder_id,
            relative_path,
            path.name,
            path.suffix.lower().lstrip("."),
            media_type,
            size_bytes,
            mtime_ns,
            preview.width,
            preview.height,
            preview.state,
            preview.content,
            preview.media_type,
            preview.error,
            PREVIEW_REVISION,
            generation,
        ),
    )


def scan_catalog(
    settings: CatalogSettings,
    *,
    progress: ProgressCallback | None = None,
) -> ScanSummary:
    photo_root = settings.photo_root.resolve()
    edit_folders = discover_edit_folders(photo_root)
    initialize_database(settings.database_path)

    connection = connect_database(settings.database_path)
    generated_previews = 0
    reused_files = 0
    try:
        generation = next_generation(connection)
        fingerprints = existing_file_fingerprints(connection)

        for index, edit_folder in enumerate(edit_folders, start=1):
            source_path = edit_folder.relative_to(photo_root).as_posix()
            if progress:
                progress(
                    ScanProgress(
                        current=index,
                        total=len(edit_folders),
                        source_path=source_path,
                    )
                )

            folder_id = upsert_folder(
                connection,
                source_path=source_path,
                camera=edit_folder.parent.parent.name,
                date_label=edit_folder.parent.name,
                generation=generation,
            )

            for path in iter_folder_files(edit_folder):
                relative_path = path.relative_to(edit_folder).as_posix()
                stat = path.stat()
                fingerprint = fingerprints.get((source_path, relative_path))
                if fingerprint and fingerprint[1:] == (
                    stat.st_size,
                    stat.st_mtime_ns,
                    PREVIEW_REVISION,
                ):
                    connection.execute(
                        """
                        UPDATE media_files
                        SET seen_generation = ?
                        WHERE id = ?
                        """,
                        (generation, fingerprint[0]),
                    )
                    reused_files += 1
                    continue

                media_type = mimetypes.guess_type(path.name)[0]
                preview = create_preview(
                    path,
                    media_type or "application/octet-stream",
                )
                upsert_file(
                    connection,
                    folder_id=folder_id,
                    relative_path=relative_path,
                    path=path,
                    size_bytes=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                    media_type=media_type or "application/octet-stream",
                    preview=preview,
                    generation=generation,
                )
                if preview.state == "ready":
                    generated_previews += 1

        finish_generation(
            connection,
            generation=generation,
            photo_root=photo_root,
        )
        connection.commit()

        stats = catalog_stats(connection)
        return ScanSummary(
            folder_count=stats["folder_count"],
            file_count=stats["file_count"],
            total_bytes=stats["total_bytes"],
            preview_count=stats["preview_count"],
            error_count=stats["error_count"],
            generated_previews=generated_previews,
            reused_files=reused_files,
        )
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
