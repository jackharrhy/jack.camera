from typing import Dict
from pathlib import Path
import shutil

import typer
import toml
from pydantic import BaseModel
from exif import Image


class Photo(BaseModel):
    src: str
    make: str | None
    model: str | None
    iso: int | None
    f_stop: int | None
    focal_length: int | None
    exposure_time: int | None


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


@app.command()
def parse_and_produce():
    info_path = Path("./info.toml")

    info = Info(**toml.loads(info_path.read_text()))

    for page_id, page in info.pages.items():
        location_type, location_key = page.location.split(":")

        page_outdir = photos_output / page_id
        page_outdir.mkdir(parents=True, exist_ok=True)
        (page_outdir / "assets").mkdir(parents=True, exist_ok=True)

        if location_type == "local":
            for asset_id, asset in page.assets.items():
                asset_srcpath = Path(location_key) / asset.src

                asset_outpath = (
                    page_outdir / "assets" / f"{asset_id}{asset_srcpath.suffix}"
                )
                print(f"{page_id} - {asset_id}: {asset_srcpath} -> {asset_outpath}")
                shutil.copy(asset_srcpath, asset_outpath)

            for photo_id, photo in page.photos.items():
                photo_srcpath = Path(location_key) / photo.src
                image = Image(photo_srcpath)

                photo.make = image.make
                photo.model = image.model
                photo.iso = image.photographic_sensitivity
                photo.f_stop = image.f_number
                photo.focal_length = image.focal_length
                photo.exposure_time = image.exposure_time

                photo_outpath = page_outdir / f"{photo_id}{photo_srcpath.suffix}"

                print(f"{page_id} - {photo_id}: {photo_srcpath} -> {photo_outpath}")
                shutil.copy(photo_srcpath, photo_outpath)
        else:
            raise Exception("Unknown location type")

    Path("./src/info.json").write_text(info.json())


if __name__ == "__main__":
    app()
