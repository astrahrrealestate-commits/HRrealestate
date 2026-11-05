import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    root: path.resolve(__dirname),
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async redirects() {
    return [
      {
        source: "/messages",
        destination: "/inbox",
        permanent: true,
      },
      {
        source: "/messages/:path*",
        destination: "/inbox/:path*",
        permanent: true,
      },
    ];
  },
  async rewrites() {
    return [
      {
        source: "/messages",
        destination: "/inbox",
      },
      {
        source: "/messages/:path*",
        destination: "/inbox/:path*",
      },
    ];
  },
};

export default nextConfig;
