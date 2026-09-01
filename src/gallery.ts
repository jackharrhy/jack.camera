import info from "./info.json";

export interface Dimensions {
  width: number;
  height: number;
}

export interface MediaInfo {
  src: string;
  dimensions: Dimensions;
  small_dimensions: Dimensions;
}

export interface PhotoInfo extends MediaInfo {
  make: string;
  model: string;
  iso: number;
  f_stop: number;
  focal_length: number;
  exposure_time: number;
}

export interface GalleryInfo {
  title: string;
  date: string;
  location: string;
  photos: Record<string, PhotoInfo>;
  assets: Record<string, MediaInfo>;
}

export const galleries = info.pages as Record<string, GalleryInfo>;

export function getGalleryMedia(page: string, key: string) {
  const gallery = galleries[page];

  return gallery?.photos[key] ?? gallery?.assets[key];
}
