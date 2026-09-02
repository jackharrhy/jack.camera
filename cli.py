from __future__ import annotations

from dataclasses import dataclass
import filecmp
import os
from pathlib import Path
import shutil
import tomllib
from typing import Annotated

from exif import Image
from PIL import Image as PILImage, ImageOps
from pydantic import BaseModel, Field, field_validator
import typer


INFO_PATH = Path("info.toml")
DATA_ROOT = Path("data")
PHOTOS_OUTPUT = Path("public/photos")
GENERATED_INFO_PATH = Path("src/info.json")
DEFAULT_PHOTO_ROOT = Path(
    os.environ.get("JACK_CAMERA_PHOTO_ROOT", "/mnt/stash/photo")
)


def validate_relative_path(path: Path) -> Path:
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("must be a relative path without '..'")
    return path


class Dimensions(BaseModel):
    width: int
    height: int


class Photo(BaseModel):
    src: str
    make: str | None = None
    model: str | None = None
    iso: int | None = None
    f_stop: float | None = None
    focal_length: float | None = None
    exposure_time: float | None = None
    dimensions: Dimensions | None = None
    small_dimensions: Dimensions | None = None

    @field_validator("src")
    @classmethod
    def src_is_relative(cls, value: str) -> str:
        validate_relative_path(Path(value))
        return value


class Asset(BaseModel):
    src: str
    dimensions: Dimensions | None = None
    small_dimensions: Dimensions | None = None

    @field_validator("src")
    @classmethod
    def src_is_relative(cls, value: str) -> str:
        validate_relative_path(Path(value))
        return value


class Page(BaseModel):
    title: str
    date: str
    source: Path = Field(exclude=True)
    photos: dict[str, Photo] = Field(default_factory=dict)
    assets: dict[str, Asset] = Field(default_factory=dict)

    @field_validator("source")
    @classmethod
    def source_is_relative(cls, value: Path) -> Path:
        return validate_relative_path(value)


class Info(BaseModel):
    pages: dict[str, Page]


@dataclass(frozen=True)
class CopyItem:
    source: Path
    destination: Path
    description: str


app = typer.Typer(no_args_is_help=True)


def load_info(info_path: Path = INFO_PATH) -> Info:
    return Info.model_validate(tomllib.loads(info_path.read_text()))


def write_text_atomically(path: Path, content: str) -> None:
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(content)
    temporary_path.replace(path)


def select_pages(
    info: Info, requested_page_ids: list[str] | None
) -> list[tuple[str, Page]]:
    if not requested_page_ids:
        return list(info.pages.items())

    unknown_pages = sorted(set(requested_page_ids) - info.pages.keys())
    if unknown_pages:
        raise ValueError(f"unknown gallery: {', '.join(unknown_pages)}")

    return [(page_id, info.pages[page_id]) for page_id in requested_page_ids]


def build_hydration_plan(
    pages: list[tuple[str, Page]],
    photo_root: Path,
    data_root: Path,
) -> tuple[list[CopyItem], list[str]]:
    plan: list[CopyItem] = []
    errors: list[str] = []

    if not photo_root.is_dir():
        errors.append(f"photo root is not a directory: {photo_root}")

    for page_id, page in pages:
        source = photo_root / page.source
        for photo_id, photo in page.photos.items():
            plan.append(
                CopyItem(
                    source=source / photo.src,
                    destination=data_root / page_id / photo.src,
                    description=f"{page_id} photo {photo_id}",
                )
            )

        for asset_id, asset in page.assets.items():
            plan.append(
                CopyItem(
                    source=source / asset.src,
                    destination=data_root / page_id / asset.src,
                    description=f"{page_id} asset {asset_id}",
                )
            )

    return plan, errors


def preflight_copy_plan(
    plan: list[CopyItem], initial_errors: list[str]
) -> tuple[list[CopyItem], int, list[str]]:
    to_copy: list[CopyItem] = []
    current_count = 0
    errors = list(initial_errors)

    for item in plan:
        if not item.source.is_file():
            errors.append(f"missing source for {item.description}: {item.source}")
            continue

        if not item.destination.exists():
            to_copy.append(item)
            continue

        if not item.destination.is_file():
            errors.append(
                f"destination is not a file for {item.description}: {item.destination}"
            )
            continue

        if filecmp.cmp(item.source, item.destination, shallow=False):
            current_count += 1
        else:
            errors.append(
                f"destination differs for {item.description}: {item.destination}"
            )

    return to_copy, current_count, errors


def print_errors(errors: list[str]) -> None:
    typer.echo("Hydration aborted; no files were copied:", err=True)
    for error in errors:
        typer.echo(f"  - {error}", err=True)


@app.command()
def hydrate(
    page: Annotated[
        list[str] | None,
        typer.Option("--page", "-p", help="Hydrate only this gallery; repeatable."),
    ] = None,
    photo_root: Annotated[
        Path,
        typer.Option(
            help="NAS photo root (or set JACK_CAMERA_PHOTO_ROOT).",
            file_okay=False,
        ),
    ] = DEFAULT_PHOTO_ROOT,
    data_root: Annotated[
        Path,
        typer.Option(help="Local destination for source gallery files."),
    ] = DATA_ROOT,
    dry_run: Annotated[
        bool,
        typer.Option(help="Validate and report without copying files."),
    ] = False,
) -> None:
    """Copy manifest-selected source files from the NAS into local data."""
    try:
        pages = select_pages(load_info(), page)
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error

    for page_id, gallery in pages:
        typer.echo(f"{page_id}: {photo_root / gallery.source}")

    plan, mapping_errors = build_hydration_plan(pages, photo_root.resolve(), data_root)
    to_copy, current_count, errors = preflight_copy_plan(plan, mapping_errors)
    if errors:
        print_errors(errors)
        raise typer.Exit(code=1)

    if dry_run:
        typer.echo(
            f"Ready: {len(to_copy)} files to copy, {current_count} already current."
        )
        return

    for item in to_copy:
        item.destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item.source, item.destination)

    typer.echo(
        f"Hydrated {len(to_copy)} files; {current_count} were already current."
    )


def create_small_image(
    src_path: Path, out_path: Path, max_width: int = 2000
) -> None:
    """Create a smaller rendition using the project's pinned Pillow dependency."""
    with PILImage.open(src_path) as source_image:
        resized_image = ImageOps.exif_transpose(source_image)
        if resized_image.width > max_width:
            resized_image.thumbnail(
                (max_width, resized_image.height), PILImage.Resampling.LANCZOS
            )

        save_options: dict[str, bool | int] = {"optimize": True}
        if out_path.suffix.lower() in {".jpg", ".jpeg"}:
            if resized_image.mode not in {"RGB", "L"}:
                resized_image = resized_image.convert("RGB")
            save_options.update(quality=85, progressive=True)

        resized_image.save(out_path, **save_options)


def process_asset(
    asset_id: str,
    asset: Asset,
    src_dir: Path,
    page_id: str,
    page_outdir: Path,
) -> None:
    """Process a single asset: copy original and create small version."""
    asset_srcpath = src_dir / asset.src
    asset_outpath = page_outdir / "assets" / f"{asset_id}{asset_srcpath.suffix}"

    print(f"{page_id} - {asset_id}: {asset_srcpath} -> {asset_outpath}")
    shutil.copy2(asset_srcpath, asset_outpath)

    with PILImage.open(asset_srcpath) as pil_image:
        asset.dimensions = Dimensions(width=pil_image.width, height=pil_image.height)

    small_outpath = asset_outpath.parent / f"{asset_id}.small{asset_srcpath.suffix}"
    create_small_image(asset_srcpath, small_outpath)

    with PILImage.open(small_outpath) as pil_image:
        asset.small_dimensions = Dimensions(
            width=pil_image.width, height=pil_image.height
        )


def process_photo(
    photo_id: str,
    photo: Photo,
    src_dir: Path,
    page_id: str,
    page_outdir: Path,
) -> None:
    """Extract EXIF, copy the original, and create a smaller rendition."""
    photo_srcpath = src_dir / photo.src
    image = Image(photo_srcpath)

    photo.make = image.make
    photo.model = image.model
    photo.iso = int(image.photographic_sensitivity)
    photo.f_stop = float(image.f_number)
    photo.focal_length = float(image.focal_length)
    photo.exposure_time = float(image.exposure_time)

    with PILImage.open(photo_srcpath) as pil_image:
        photo.dimensions = Dimensions(width=pil_image.width, height=pil_image.height)

    photo_outpath = page_outdir / f"{photo_id}{photo_srcpath.suffix}"

    print(f"{page_id} - {photo_id}: {photo_srcpath} -> {photo_outpath}")
    shutil.copy2(photo_srcpath, photo_outpath)

    small_outpath = photo_outpath.parent / f"{photo_id}.small{photo_srcpath.suffix}"
    create_small_image(photo_srcpath, small_outpath)

    with PILImage.open(small_outpath) as pil_image:
        photo.small_dimensions = Dimensions(
            width=pil_image.width, height=pil_image.height
        )


def validate_local_data(info: Info, data_root: Path) -> list[str]:
    errors: list[str] = []
    for page_id, page in info.pages.items():
        src_dir = data_root / page_id
        for photo_id, photo in page.photos.items():
            source = src_dir / photo.src
            if not source.is_file():
                errors.append(f"missing {page_id} photo {photo_id}: {source}")
        for asset_id, asset in page.assets.items():
            source = src_dir / asset.src
            if not source.is_file():
                errors.append(f"missing {page_id} asset {asset_id}: {source}")
    return errors


def process_page(page_id: str, page: Page, data_root: Path, photos_output: Path) -> None:
    """Create output directories and process a gallery's assets and photos."""
    src_dir = data_root / page_id
    page_outdir = photos_output / page_id
    page_outdir.mkdir(parents=True, exist_ok=True)
    (page_outdir / "assets").mkdir(parents=True, exist_ok=True)

    for asset_id, asset in page.assets.items():
        process_asset(asset_id, asset, src_dir, page_id, page_outdir)

    for photo_id, photo in page.photos.items():
        process_photo(photo_id, photo, src_dir, page_id, page_outdir)


@app.command("parse-and-produce")
def parse_and_produce(
    data_root: Annotated[
        Path,
        typer.Option(help="Local source gallery directory."),
    ] = DATA_ROOT,
    photos_output: Annotated[
        Path,
        typer.Option(help="Generated public photo directory."),
    ] = PHOTOS_OUTPUT,
    generated_info: Annotated[
        Path,
        typer.Option(help="Generated Astro gallery metadata file."),
    ] = GENERATED_INFO_PATH,
) -> None:
    """Build public renditions and generated frontend metadata."""
    info = load_info()
    errors = validate_local_data(info, data_root)
    if errors:
        typer.echo("Production aborted; local source data is incomplete:", err=True)
        for error in errors:
            typer.echo(f"  - {error}", err=True)
        raise typer.Exit(code=1)

    for page_id, page in info.pages.items():
        process_page(page_id, page, data_root, photos_output)

    write_text_atomically(generated_info, info.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    app()
