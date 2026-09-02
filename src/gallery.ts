import {
  getCollection,
  getEntry,
  type CollectionEntry,
} from "astro:content";

export type Gallery = CollectionEntry<"galleries">;
export type GalleryPhoto = Gallery["data"]["photos"][string];
export type GalleryAsset = Gallery["data"]["assets"][string];
export type GalleryMediaKind = "photos" | "assets";

export type GalleryMedia =
  | { kind: "photos"; id: string; data: GalleryPhoto }
  | { kind: "assets"; id: string; data: GalleryAsset };

const MEDIA_BASE_URL = import.meta.env.PROD
  ? "https://files.jack.camera"
  : "/photos";

export async function listGalleries() {
  const galleries = await getCollection("galleries");

  return galleries.sort((left, right) =>
    right.data.date.localeCompare(left.data.date),
  );
}

export async function requireGallery(id: string) {
  const gallery = await getEntry("galleries", id);

  if (!gallery) {
    throw new Error(`Gallery not found: ${id}`);
  }

  return gallery;
}

export function requireGalleryMedia(
  gallery: Gallery,
  kind: GalleryMediaKind,
  id: string,
): GalleryMedia {
  if (kind === "photos") {
    const data = gallery.data.photos[id];
    if (data) return { kind, id, data };
  } else {
    const data = gallery.data.assets[id];
    if (data) return { kind, id, data };
  }

  throw new Error(`Media not found: ${gallery.id}/${kind}/${id}`);
}

export function listGalleryMedia(gallery: Gallery): GalleryMedia[] {
  const photos: GalleryMedia[] = Object.entries(gallery.data.photos).map(
    ([id, data]) => ({ kind: "photos", id, data }),
  );
  const assets: GalleryMedia[] = Object.entries(gallery.data.assets).map(
    ([id, data]) => ({ kind: "assets", id, data }),
  );

  return [...assets, ...photos];
}

export function mediaDetailPath(
  gallery: Gallery,
  kind: GalleryMediaKind,
  id: string,
) {
  return `/${gallery.id}/${mediaRouteId(kind, id)}`;
}

export function mediaRouteId(kind: GalleryMediaKind, id: string) {
  return kind === "assets" ? `assets-${id}` : id;
}

export function mediaFileUrl(
  gallery: Gallery,
  media: GalleryMedia,
  variant: "small" | "full" = "full",
) {
  const extension = media.data.src.split(".").pop();

  if (!extension) {
    throw new Error(`Media has no file extension: ${media.data.src}`);
  }

  const directory = media.kind === "assets" ? "assets/" : "";
  const sizeMarker = variant === "small" ? ".small" : "";

  return `${MEDIA_BASE_URL}/${gallery.id}/${directory}${media.id}${sizeMarker}.${extension}`;
}

export function mediaAlt(id: string) {
  return id.replaceAll("-", " ");
}

export function formatPhotoDetails(photo: GalleryPhoto) {
  const shutterSpeed =
    photo.exposure_time < 1
      ? `1/${Math.round(1 / photo.exposure_time)}s`
      : `${photo.exposure_time}s`;

  return `${photo.make} ${photo.model} / ISO ${photo.iso} / f${photo.f_stop} / ${photo.focal_length}mm / ${shutterSpeed}`;
}
