import { defineCollection } from "astro:content";
import { file } from "astro/loaders";
import { z } from "astro/zod";

const dimensionsSchema = z.object({
  width: z.number().int().positive(),
  height: z.number().int().positive(),
});

const mediaSchema = z.object({
  src: z.string().min(1),
  dimensions: dimensionsSchema,
  small_dimensions: dimensionsSchema,
});

const photoSchema = mediaSchema.extend({
  make: z.string().min(1),
  model: z.string().min(1),
  iso: z.number().int().positive(),
  f_stop: z.number().positive(),
  focal_length: z.number().positive(),
  exposure_time: z.number().positive(),
});

const gallerySchema = z.object({
  title: z.string().min(1),
  date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  photos: z.record(z.string(), photoSchema),
  assets: z.record(z.string(), mediaSchema),
});

const infoSchema = z.object({
  pages: z.record(z.string(), gallerySchema),
});

const galleries = defineCollection({
  loader: file("src/info.json", {
    parser: (text) => infoSchema.parse(JSON.parse(text)).pages,
  }),
  schema: gallerySchema,
});

export const collections = { galleries };
