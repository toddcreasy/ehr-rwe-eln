import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static files only: FastAPI serves frontend/out at /.
  output: "export",
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
