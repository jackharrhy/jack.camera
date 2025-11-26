import { defineConfig } from "astro/config";

// https://astro.build/config
export default defineConfig({
  image: {
    domains: ["jack.camera", "localhost:4321"],
  },
});
