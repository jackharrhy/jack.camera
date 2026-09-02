from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog_meta (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    generation INTEGER NOT NULL DEFAULT 0,
    scanned_at TEXT,
    photo_root TEXT
);

INSERT OR IGNORE INTO catalog_meta (singleton) VALUES (1);

CREATE TABLE IF NOT EXISTS edit_folders (
    id INTEGER PRIMARY KEY,
    source_path TEXT NOT NULL UNIQUE,
    camera TEXT NOT NULL,
    date_label TEXT NOT NULL,
    capture_date TEXT,
    seen_generation INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS media_files (
    id INTEGER PRIMARY KEY,
    folder_id INTEGER NOT NULL REFERENCES edit_folders(id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    extension TEXT NOT NULL,
    media_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    mtime_ns INTEGER NOT NULL,
    width INTEGER,
    height INTEGER,
    preview_state TEXT NOT NULL CHECK (
        preview_state IN ('ready', 'unsupported', 'error')
    ),
    thumbnail BLOB,
    thumbnail_mime TEXT,
    preview_error TEXT,
    preview_revision INTEGER NOT NULL,
    seen_generation INTEGER NOT NULL,
    UNIQUE (folder_id, relative_path),
    CHECK (
        preview_state != 'ready'
        OR (
            thumbnail IS NOT NULL
            AND thumbnail_mime IS NOT NULL
            AND width IS NOT NULL
            AND height IS NOT NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS media_files_folder_path
ON media_files(folder_id, relative_path);

CREATE INDEX IF NOT EXISTS edit_folders_camera_date
ON edit_folders(camera, capture_date);
"""


class CatalogVersionError(RuntimeError):
    pass


def connect_database(
    database_path: Path, *, read_only: bool = False
) -> sqlite3.Connection:
    if read_only:
        connection = sqlite3.connect(
            f"file:{database_path}?mode=ro",
            uri=True,
            autocommit=True,
        )
    else:
        connection = sqlite3.connect(database_path, autocommit=False)

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def initialize_database(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, autocommit=True)
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in {0, SCHEMA_VERSION}:
            raise CatalogVersionError(
                f"catalog schema {version} is not supported; expected {SCHEMA_VERSION}"
            )

        connection.executescript(SCHEMA)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    finally:
        connection.close()


def next_generation(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT generation FROM catalog_meta WHERE singleton = 1"
    ).fetchone()
    assert row is not None
    return int(row["generation"]) + 1


def finish_generation(
    connection: sqlite3.Connection,
    *,
    generation: int,
    photo_root: Path,
) -> None:
    connection.execute(
        "DELETE FROM media_files WHERE seen_generation != ?",
        (generation,),
    )
    connection.execute(
        "DELETE FROM edit_folders WHERE seen_generation != ?",
        (generation,),
    )
    connection.execute(
        """
        UPDATE catalog_meta
        SET generation = ?, scanned_at = ?, photo_root = ?
        WHERE singleton = 1
        """,
        (generation, datetime.now(UTC).isoformat(), str(photo_root)),
    )


def existing_file_fingerprints(
    connection: sqlite3.Connection,
) -> dict[tuple[str, str], tuple[int, int, int, int]]:
    rows = connection.execute(
        """
        SELECT
            folder.source_path,
            media.relative_path,
            media.id,
            media.size_bytes,
            media.mtime_ns,
            media.preview_revision
        FROM media_files AS media
        JOIN edit_folders AS folder ON folder.id = media.folder_id
        """
    )
    return {
        (row["source_path"], row["relative_path"]): (
            row["id"],
            row["size_bytes"],
            row["mtime_ns"],
            row["preview_revision"],
        )
        for row in rows
    }


def catalog_stats(connection: sqlite3.Connection) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM edit_folders) AS folder_count,
            (SELECT COUNT(*) FROM media_files) AS file_count,
            (SELECT COALESCE(SUM(size_bytes), 0) FROM media_files) AS total_bytes,
            (
                SELECT COUNT(*) FROM media_files
                WHERE preview_state = 'ready'
            ) AS preview_count,
            (
                SELECT COUNT(*) FROM media_files
                WHERE preview_state = 'error'
            ) AS error_count,
            meta.scanned_at,
            meta.photo_root
        FROM catalog_meta AS meta
        WHERE meta.singleton = 1
        """
    ).fetchone()
    assert row is not None
    return row


def folder_filters(
    connection: sqlite3.Connection,
) -> tuple[list[str], list[str]]:
    cameras = [
        row["camera"]
        for row in connection.execute(
            "SELECT DISTINCT camera FROM edit_folders ORDER BY camera"
        )
    ]
    years = [
        row["year"]
        for row in connection.execute(
            """
            SELECT DISTINCT substr(capture_date, 1, 4) AS year
            FROM edit_folders
            WHERE capture_date IS NOT NULL
            ORDER BY year DESC
            """
        )
    ]
    return cameras, years


def list_folders(
    connection: sqlite3.Connection,
    *,
    camera: str | None = None,
    year: str | None = None,
) -> list[sqlite3.Row]:
    return list(
        connection.execute(
            """
            SELECT
                folder.*,
                COUNT(media.id) AS file_count,
                COALESCE(SUM(media.size_bytes), 0) AS total_bytes,
                COALESCE(SUM(media.preview_state = 'ready'), 0) AS preview_count,
                (
                    SELECT candidate.id
                    FROM media_files AS candidate
                    WHERE
                        candidate.folder_id = folder.id
                        AND candidate.preview_state = 'ready'
                    ORDER BY candidate.relative_path
                    LIMIT 1
                ) AS cover_file_id
            FROM edit_folders AS folder
            LEFT JOIN media_files AS media ON media.folder_id = folder.id
            WHERE
                (? IS NULL OR folder.camera = ?)
                AND (
                    ? IS NULL
                    OR substr(folder.capture_date, 1, 4) = ?
                )
            GROUP BY folder.id
            ORDER BY
                folder.capture_date IS NULL,
                folder.capture_date DESC,
                folder.source_path DESC
            """,
            (camera, camera, year, year),
        )
    )


def get_folder(connection: sqlite3.Connection, folder_id: int) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT
            folder.*,
            COUNT(media.id) AS file_count,
            COALESCE(SUM(media.size_bytes), 0) AS total_bytes,
            COALESCE(SUM(media.preview_state = 'ready'), 0) AS preview_count
        FROM edit_folders AS folder
        LEFT JOIN media_files AS media ON media.folder_id = folder.id
        WHERE folder.id = ?
        GROUP BY folder.id
        """,
        (folder_id,),
    ).fetchone()


def list_folder_files(
    connection: sqlite3.Connection, folder_id: int
) -> list[sqlite3.Row]:
    return list(
        connection.execute(
            """
            SELECT
                id,
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
                preview_error
            FROM media_files
            WHERE folder_id = ?
            ORDER BY relative_path
            """,
            (folder_id,),
        )
    )


def get_media_file(connection: sqlite3.Connection, file_id: int) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT
            media.id,
            media.relative_path,
            media.filename,
            media.media_type,
            media.size_bytes,
            media.mtime_ns,
            media.width,
            media.height,
            media.preview_state,
            media.preview_error,
            folder.source_path
        FROM media_files AS media
        JOIN edit_folders AS folder ON folder.id = media.folder_id
        WHERE media.id = ?
        """,
        (file_id,),
    ).fetchone()


def get_thumbnail(connection: sqlite3.Connection, file_id: int) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT preview_state, thumbnail, thumbnail_mime
        FROM media_files
        WHERE id = ?
        """,
        (file_id,),
    ).fetchone()
