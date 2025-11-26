from typing import Dict
from pathlib import Path
import shutil
import subprocess

import typer
import toml
from pydantic import BaseModel
from exif import Image


class Photo(BaseModel):
    src: str
    make: str | None = None
    model: str | None = None
    iso: int | None = None
    f_stop: float | None = None
    focal_length: float | None = None
    exposure_time: float | None = None


class Asset(BaseModel):
    src: str


class Page(BaseModel):
    title: str
    date: str
    location: str
    photos: Dict[str, Photo]
    assets: Dict[str, Asset]


class Info(BaseModel):
    pages: Dict[str, Page]


app = typer.Typer()

photos_output = Path("./public/photos")


def create_small_image(
    src_path: Path, out_path: Path, max_width: str = "2000x", max_size: str = "1MB"
):
    """Create a smaller version of an image with file size limiting."""
    subprocess.run(
        [
            "magick",
            str(src_path),
            "-resize",
            max_width,
            "-define",
            f"jpeg:extent={max_size}",
            "-quality",
            "85",
            str(out_path),
        ],
        check=True,
    )


def process_asset(
    asset_id: str,
    asset: Asset,
    src_dir: Path,
    page_id: str,
    page_outdir: Path,
):
    """Process a single asset: copy original and create small version."""
    asset_srcpath = src_dir / asset.src
    asset_outpath = page_outdir / "assets" / f"{asset_id}{asset_srcpath.suffix}"

    print(f"{page_id} - {asset_id}: {asset_srcpath} -> {asset_outpath}")
    shutil.copy(asset_srcpath, asset_outpath)

    small_outpath = asset_outpath.parent / f"{asset_id}.small{asset_srcpath.suffix}"
    create_small_image(asset_srcpath, small_outpath)


def process_photo(
    photo_id: str,
    photo: Photo,
    src_dir: Path,
    page_id: str,
    page_outdir: Path,
):
    """Process a single photo: extract EXIF data, copy original, and create small version."""
    photo_srcpath = src_dir / photo.src
    image = Image(photo_srcpath)

    photo.make = image.make
    photo.model = image.model
    photo.iso = int(image.photographic_sensitivity)
    photo.f_stop = float(image.f_number)
    photo.focal_length = float(image.focal_length)
    photo.exposure_time = float(image.exposure_time)

    photo_outpath = page_outdir / f"{photo_id}{photo_srcpath.suffix}"

    print(f"{page_id} - {photo_id}: {photo_srcpath} -> {photo_outpath}")
    shutil.copy(photo_srcpath, photo_outpath)

    small_outpath = photo_outpath.parent / f"{photo_id}.small{photo_srcpath.suffix}"
    create_small_image(photo_srcpath, small_outpath)


def process_page(page_id: str, page: Page):
    """Process a single page: create directories and process all assets and photos."""
    location_type, location_key = page.location.split(":")

    page_outdir = photos_output / page_id
    page_outdir.mkdir(parents=True, exist_ok=True)
    (page_outdir / "assets").mkdir(parents=True, exist_ok=True)

    if location_type == "local":
        src_dir = Path(location_key)

        for asset_id, asset in page.assets.items():
            process_asset(asset_id, asset, src_dir, page_id, page_outdir)

        for photo_id, photo in page.photos.items():
            process_photo(photo_id, photo, src_dir, page_id, page_outdir)
    else:
        raise Exception("Unknown location type")


@app.command()
def parse_and_produce():
    info_path = Path("./info.toml")

    info = Info(**toml.loads(info_path.read_text()))

    for page_id, page in info.pages.items():
        process_page(page_id, page)

    Path("./src/info.json").write_text(info.model_dump_json(indent=2))


if __name__ == "__main__":
    app()
