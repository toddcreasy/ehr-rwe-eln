import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static files only: FastAPI serves frontend/out at /.
  output: "export",
  // Emits /dq/index.html rather than /dq.html: FastAPI's static files serve a folder's index.
  trailingSlash: true,
  // When this build ran, in UTC; the footer shows it in the visitor's own timezone. The image
  // builds the frontend on CodeBuild, so on the public site this is the release time.
  env: { RELEASED_AT: new Date().toISOString() },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
