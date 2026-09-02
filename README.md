# jack.camera

https://jack.camera/

Some code here references my network NAS / CloudFlare buckets directly, so not psosible
for others to run it locally most likely, but hey! you can still gawk at the code :)

## Setup

```sh
mise trust
mise install
mise run setup
```

## Commands

```sh
mise run hydrate  # copy selected sources from the NAS into data/
mise run produce  # generate public renditions and src/info.json
mise run dev      # start Astro at http://localhost:4321
mise run check    # type-check and build
```

The NAS photo share defaults to `/mnt/stash/photo`. Set
`JACK_CAMERA_PHOTO_ROOT` to use another mount point.

## Galleries

- `info.toml` defines galleries, media, and NAS source paths.
- `src/galleries` contains each gallery's explicit composition.
- `src/components` contains shared gallery primitives.
- `src/info.json` is generated; do not edit it manually.

Each gallery source points to an `edits` directory. Photos live directly in it
and supporting artwork lives in `edits/assets`.

Published renditions are also backed up in the `camera` rclone remote.
