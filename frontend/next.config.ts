import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static files only: Amplify serves manual (non-Git) deployments without a server.
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
