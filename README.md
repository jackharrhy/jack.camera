# jack.camera

https://jack.camera/

## Setup

The project uses [mise](https://mise.jdx.dev/) to pin Node.js and uv.

```sh
mise trust
mise install
mise run setup
```

`mise run setup` installs both the Astro application dependencies and the
Python photo-processing dependencies.

## Development

```sh
mise run dev
```

The development site is available at http://localhost:4321. Local gallery
images are served from `public/photos`, which is intentionally not committed.

## Checks

```sh
mise run check
```

This runs Astro's type checker and creates a production build.

## Gallery architecture

`info.toml` is the editable gallery manifest. The Python pipeline enriches it
with image dimensions and EXIF metadata, then writes the generated
`src/info.json` file. Do not hand-edit the generated JSON.

Astro loads that JSON as the schema-validated `galleries` content collection in
`src/content.config.ts`. Gallery-specific composition lives in `src/galleries`,
while reusable image and layout primitives live in `src/components`. A gallery
becomes publishable when its view is added to the explicit registry in
`src/gallery-views.ts`; the homepage and static routes both use that registry.

## Photo storage

The NAS is the source of truth. Each gallery in `info.toml` has a `source` path
relative to the NAS photo share; by default that share is expected at
`/mnt/stash/photo`. Override it on another system with
`JACK_CAMERA_PHOTO_ROOT`.

| Gallery | NAS edits folder |
| --- | --- |
| `fly-fest-oct2022` | `Fujifilm XT2/2022-10-29/edits` |
| `demo-night-2-nov2025` | `Fujifilm XT2/2025-11-22/edits` |

Photos live directly in each `edits` folder. Supporting artwork lives under its
`assets` subdirectory, so the entire source bundle stays with the edited photos.
Copy only the manifest-selected sources into the ignored local `data` directory:

```sh
mise run hydrate
```

Hydration validates every source and destination before copying anything. It
does not modify the NAS, delete local files, or overwrite a differing local
file. Use the CLI directly for a dry run, a different mount point, or one
gallery:

```sh
mise exec -- uv run python cli.py hydrate --dry-run
mise exec -- uv run python cli.py hydrate \
  --photo-root /path/to/photo --page fly-fest-oct2022
```

## Published image backup

rclone is installed through mise. The Cloudflare R2 remote named `camera`
contains the currently published renditions; its credentials stay in your
user-level rclone configuration and are never committed to this repository.

```sh
mise exec -- rclone config
mise exec -- rclone listremotes
```
