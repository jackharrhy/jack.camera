export const galleryViews = {
  "demo-night-2-nov2025": () =>
    import("./galleries/demo-night-2-nov2025.astro"),
  "fly-fest-oct2022": () => import("./galleries/fly-fest-oct2022.astro"),
};

export type GalleryViewId = keyof typeof galleryViews;

export function hasGalleryView(id: string): id is GalleryViewId {
  return Object.hasOwn(galleryViews, id);
}
