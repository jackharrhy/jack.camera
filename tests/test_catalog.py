from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from jack_camera.catalog import scanner
from jack_camera.catalog.database import (
    catalog_stats,
    connect_database,
    get_media_file,
    get_thumbnail,
    list_folder_files,
    list_folders,
)
from jack_camera.catalog.scanner import CatalogScanError, scan_catalog
from jack_camera.catalog.web import create_app
from jack_camera.config import CatalogSettings


def write_image(
    path: Path,
    *,
    size: tuple[int, int] = (120, 80),
    color: str = "#c84d3d",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def build_archive(tmp_path: Path) -> CatalogSettings:
    photo_root = tmp_path / "photo"
    canon_edits = photo_root / "Canon T6i" / "2017_07_05" / "edits"
    fuji_edits = photo_root / "Fujifilm XT2" / "2025-11-22" / "edits"

    write_image(canon_edits / "IMG_001.jpg")
    write_image(canon_edits / "assets" / "poster.png", size=(60, 120))
    write_image(canon_edits / "@eaDir" / "IMG_001.jpg")
    (canon_edits / "notes.txt").write_text("remember this one")
    write_image(fuji_edits / "DSCF0001.jpg", color="#325b8a")

    return CatalogSettings(
        photo_root=photo_root,
        database_path=tmp_path / "catalog.sqlite3",
    )


def read_stats(settings: CatalogSettings):
    connection = connect_database(settings.database_path, read_only=True)
    try:
        return catalog_stats(connection)
    finally:
        connection.close()


def test_scan_catalog_stores_paths_metadata_and_thumbnail_blobs(tmp_path: Path):
    settings = build_archive(tmp_path)

    summary = scan_catalog(settings)

    assert summary.folder_count == 2
    assert summary.file_count == 4
    assert summary.preview_count == 3
    assert summary.generated_previews == 3
    assert summary.reused_files == 0
    assert summary.error_count == 0

    connection = connect_database(settings.database_path, read_only=True)
    try:
        folders = list_folders(connection)
        assert [folder["capture_date"] for folder in folders] == [
            "2025-11-22",
            "2017-07-05",
        ]

        canon = next(folder for folder in folders if folder["camera"] == "Canon T6i")
        files = list_folder_files(connection, canon["id"])
        assert [file["relative_path"] for file in files] == [
            "IMG_001.jpg",
            "assets/poster.png",
            "notes.txt",
        ]

        image = next(file for file in files if file["filename"] == "IMG_001.jpg")
        assert image["width"] == 120
        assert image["height"] == 80
        assert image["preview_state"] == "ready"
        thumbnail = get_thumbnail(connection, image["id"])
        assert thumbnail is not None
        assert thumbnail["thumbnail_mime"] == "image/jpeg"
        assert bytes(thumbnail["thumbnail"]).startswith(b"\xff\xd8")

        notes = next(file for file in files if file["filename"] == "notes.txt")
        assert notes["preview_state"] == "unsupported"
        notes_thumbnail = get_thumbnail(connection, notes["id"])
        assert notes_thumbnail is not None
        assert notes_thumbnail["thumbnail"] is None
    finally:
        connection.close()


def test_rescan_reuses_previews_and_removes_stale_rows(tmp_path: Path):
    settings = build_archive(tmp_path)
    scan_catalog(settings)

    canon_edits = settings.photo_root / "Canon T6i" / "2017_07_05" / "edits"
    (canon_edits / "notes.txt").unlink()
    write_image(canon_edits / "IMG_001.jpg", size=(200, 100), color="#27834f")

    summary = scan_catalog(settings)

    assert summary.file_count == 3
    assert summary.generated_previews == 1
    assert summary.reused_files == 2

    connection = connect_database(settings.database_path, read_only=True)
    try:
        canon = next(
            folder
            for folder in list_folders(connection)
            if folder["camera"] == "Canon T6i"
        )
        files = list_folder_files(connection, canon["id"])
        assert {file["filename"] for file in files} == {"IMG_001.jpg", "poster.png"}
        image = next(file for file in files if file["filename"] == "IMG_001.jpg")
        assert (image["width"], image["height"]) == (200, 100)
    finally:
        connection.close()


def test_failed_or_unmounted_scan_preserves_previous_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    settings = build_archive(tmp_path)
    scan_catalog(settings)
    previous_stats = dict(read_stats(settings))

    write_image(settings.photo_root / "Canon T6i" / "2017_07_05" / "edits" / "new.jpg")

    def fail_preview(_path: Path, _media_type: str):
        raise RuntimeError("simulated scanner failure")

    monkeypatch.setattr(scanner, "create_preview", fail_preview)
    with pytest.raises(RuntimeError, match="simulated scanner failure"):
        scan_catalog(settings)
    assert dict(read_stats(settings)) == previous_stats

    missing_settings = CatalogSettings(
        photo_root=tmp_path / "not-mounted",
        database_path=settings.database_path,
    )
    with pytest.raises(CatalogScanError, match="not a directory"):
        scan_catalog(missing_settings)
    assert dict(read_stats(settings)) == previous_stats

    empty_settings = CatalogSettings(
        photo_root=tmp_path / "empty-photo-root",
        database_path=settings.database_path,
    )
    empty_settings.photo_root.mkdir()
    with pytest.raises(CatalogScanError, match="refusing to empty"):
        scan_catalog(empty_settings)
    assert dict(read_stats(settings)) == previous_stats


def test_catalog_web_browser_serves_lists_thumbnails_and_originals(tmp_path: Path):
    settings = build_archive(tmp_path)
    scan_catalog(settings)
    app = create_app(settings)

    connection = connect_database(settings.database_path, read_only=True)
    try:
        folder = list_folders(connection)[0]
        media = next(
            file
            for file in list_folder_files(connection, folder["id"])
            if file["preview_state"] == "ready"
        )
        full_media = get_media_file(connection, media["id"])
        assert full_media is not None
    finally:
        connection.close()

    with TestClient(app) as client:
        index = client.get("/")
        assert index.status_code == 200
        assert "<h1>Photos</h1>" in index.text
        assert "2 folders," in index.text
        assert "SQLite" not in index.text

        filtered = client.get("/", params={"camera": "Fujifilm XT2", "year": "2025"})
        assert filtered.status_code == 200
        assert "2025-11-22" in filtered.text
        assert "2017-07-05" not in filtered.text

        detail = client.get(f"/folders/{folder['id']}")
        assert detail.status_code == 200
        assert folder["source_path"] in detail.text

        thumbnail = client.get(f"/thumbnails/{media['id']}")
        assert thumbnail.status_code == 200
        assert thumbnail.headers["content-type"] == "image/jpeg"
        assert thumbnail.content.startswith(b"\xff\xd8")

        original = client.get(f"/files/{media['id']}/original")
        assert original.status_code == 200
        assert (
            original.content
            == (
                settings.photo_root
                / full_media["source_path"]
                / full_media["relative_path"]
            ).read_bytes()
        )

        assert client.get("/folders/999999").status_code == 404
        assert client.get("/thumbnails/999999").status_code == 404
        assert client.get("/favicon.ico").status_code == 200
        assert client.get("/healthz").json() == {
            "database": True,
            "photo_root": True,
        }
