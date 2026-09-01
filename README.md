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
