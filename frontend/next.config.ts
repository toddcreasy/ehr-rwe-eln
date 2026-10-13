import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static files only: FastAPI serves frontend/out at /.
  output: "export",
  // Emits /dq/index.html rather than /dq.html: FastAPI's static files serve a folder's index.
  trailingSlash: true,
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
