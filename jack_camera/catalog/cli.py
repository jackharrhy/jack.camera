from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from jack_camera.catalog.formatting import human_bytes
from jack_camera.catalog.scanner import CatalogScanError, ScanProgress, scan_catalog
from jack_camera.catalog.web import create_app
from jack_camera.config import CatalogSettings

app = typer.Typer(no_args_is_help=True)


def resolve_settings(
    photo_root: Path | None,
    database: Path | None,
) -> CatalogSettings:
    defaults = CatalogSettings.from_env()
    return CatalogSettings(
        photo_root=photo_root or defaults.photo_root,
        database_path=database or defaults.database_path,
    )


@app.command()
def scan(
    photo_root: Annotated[
        Path | None,
        typer.Option(help="NAS photo root; defaults to JACK_CAMERA_PHOTO_ROOT."),
    ] = None,
    database: Annotated[
        Path | None,
        typer.Option(help="Local SQLite catalog path."),
    ] = None,
) -> None:
    """Refresh the local catalog and its SQLite thumbnail BLOBs."""
    settings = resolve_settings(photo_root, database)

    def report(update: ScanProgress) -> None:
        typer.echo(f"[{update.current}/{update.total}] {update.source_path}")

    try:
        summary = scan_catalog(settings, progress=report)
    except CatalogScanError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error

    typer.echo(
        "Cataloged "
        f"{summary.folder_count} folders and {summary.file_count} files "
        f"({human_bytes(summary.total_bytes)}); "
        f"{summary.preview_count} previews ready, "
        f"{summary.generated_previews} generated, "
        f"{summary.reused_files} unchanged files reused, "
        f"{summary.error_count} preview errors."
    )


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Address to listen on.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 8000,
    photo_root: Annotated[
        Path | None,
        typer.Option(help="NAS photo root; defaults to JACK_CAMERA_PHOTO_ROOT."),
    ] = None,
    database: Annotated[
        Path | None,
        typer.Option(help="Local SQLite catalog path."),
    ] = None,
) -> None:
    """Serve the local photo catalog browser."""
    settings = resolve_settings(photo_root, database)
    uvicorn.run(create_app(settings), host=host, port=port)
