from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from jack_camera.catalog.database import (
    catalog_stats,
    connect_database,
    folder_filters,
    get_folder,
    get_media_file,
    get_thumbnail,
    initialize_database,
    list_folder_files,
    list_folders,
)
from jack_camera.catalog.formatting import human_bytes, human_number
from jack_camera.config import PROJECT_ROOT, CatalogSettings

PACKAGE_ROOT = Path(__file__).resolve().parent


def open_catalog(database_path: Path) -> sqlite3.Connection:
    return connect_database(database_path, read_only=True)


def require_media_file(database_path: Path, file_id: int) -> sqlite3.Row:
    connection = open_catalog(database_path)
    try:
        media_file = get_media_file(connection, file_id)
    finally:
        connection.close()
    if media_file is None:
        raise HTTPException(status_code=404, detail="file not found")
    return media_file


def resolve_original_path(settings: CatalogSettings, media_file: sqlite3.Row) -> Path:
    photo_root = settings.photo_root.resolve()
    source_path = (
        photo_root / media_file["source_path"] / media_file["relative_path"]
    ).resolve()
    if not source_path.is_relative_to(photo_root) or not source_path.is_file():
        raise HTTPException(status_code=404, detail="file is no longer available")
    return source_path


def create_app(settings: CatalogSettings | None = None) -> FastAPI:
    resolved_settings = settings or CatalogSettings.from_env()
    templates = Jinja2Templates(directory=PACKAGE_ROOT / "templates")
    templates.env.filters["filesize"] = human_bytes
    templates.env.filters["number"] = human_number

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        initialize_database(resolved_settings.database_path)
        yield

    app = FastAPI(title="jack.camera photos", lifespan=lifespan)
    app.mount(
        "/static",
        StaticFiles(directory=PACKAGE_ROOT / "static"),
        name="static",
    )

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(PROJECT_ROOT / "public" / "favicon.ico")

    @app.get("/", response_class=HTMLResponse)
    def folder_index(
        request: Request,
        camera: str | None = Query(default=None),
        year: str | None = Query(default=None),
    ) -> HTMLResponse:
        connection = open_catalog(resolved_settings.database_path)
        try:
            stats = catalog_stats(connection)
            cameras, years = folder_filters(connection)
            folders = list_folders(connection, camera=camera, year=year)
        finally:
            connection.close()

        return templates.TemplateResponse(
            request=request,
            name="folders.html",
            context={
                "stats": stats,
                "folders": folders,
                "cameras": cameras,
                "years": years,
                "selected_camera": camera,
                "selected_year": year,
            },
        )

    @app.get("/folders/{folder_id}", response_class=HTMLResponse)
    def folder_detail(request: Request, folder_id: int) -> HTMLResponse:
        connection = open_catalog(resolved_settings.database_path)
        try:
            folder = get_folder(connection, folder_id)
            files = list_folder_files(connection, folder_id) if folder else []
        finally:
            connection.close()

        if folder is None:
            raise HTTPException(status_code=404, detail="folder not found")
        return templates.TemplateResponse(
            request=request,
            name="folder.html",
            context={"folder": folder, "files": files},
        )

    @app.get("/thumbnails/{file_id}")
    def thumbnail(file_id: int) -> Response:
        connection = open_catalog(resolved_settings.database_path)
        try:
            stored_thumbnail = get_thumbnail(connection, file_id)
        finally:
            connection.close()
        if stored_thumbnail is None:
            raise HTTPException(status_code=404, detail="file not found")
        if stored_thumbnail["preview_state"] != "ready":
            raise HTTPException(status_code=404, detail="preview not found")
        return Response(
            content=stored_thumbnail["thumbnail"],
            media_type=stored_thumbnail["thumbnail_mime"],
            headers={"Cache-Control": "private, max-age=86400"},
        )

    @app.get("/files/{file_id}/original", response_class=FileResponse)
    def original(file_id: int) -> FileResponse:
        media_file = require_media_file(resolved_settings.database_path, file_id)
        source_path = resolve_original_path(resolved_settings, media_file)
        return FileResponse(source_path, media_type=media_file["media_type"])

    @app.get("/healthz")
    def health() -> dict[str, bool]:
        return {
            "database": resolved_settings.database_path.is_file(),
            "photo_root": resolved_settings.photo_root.is_dir(),
        }

    return app


app = create_app()
