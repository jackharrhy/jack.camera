from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PHOTO_ROOT = Path(os.environ.get("JACK_CAMERA_PHOTO_ROOT", "/mnt/stash/photo"))
DEFAULT_CATALOG_PATH = Path(
    os.environ.get(
        "JACK_CAMERA_CATALOG_PATH",
        PROJECT_ROOT / ".jack-camera" / "catalog.sqlite3",
    )
)


@dataclass(frozen=True)
class CatalogSettings:
    photo_root: Path = DEFAULT_PHOTO_ROOT
    database_path: Path = DEFAULT_CATALOG_PATH

    @classmethod
    def from_env(cls) -> CatalogSettings:
        return cls(
            photo_root=Path(
                os.environ.get("JACK_CAMERA_PHOTO_ROOT", DEFAULT_PHOTO_ROOT)
            ),
            database_path=Path(
                os.environ.get("JACK_CAMERA_CATALOG_PATH", DEFAULT_CATALOG_PATH)
            ),
        )
