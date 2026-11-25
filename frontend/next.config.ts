import type { NextConfig } from "next";

import packageJson from "./package.json";

const nextConfig: NextConfig = {
  // Static files only: FastAPI serves frontend/out at /.
  output: "export",
  // Emits /dq/index.html rather than /dq.html: FastAPI's static files serve a folder's index.
  trailingSlash: true,
  // The release the footer names, and when this build ran, in UTC (shown in the visitor's own
  // timezone). The image builds the frontend on CodeBuild from a release tag, so on the public
  // site these are the release and its build time. A release bumps the version in package.json.
  env: { RELEASE_VERSION: packageJson.version, RELEASED_AT: new Date().toISOString() },
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
