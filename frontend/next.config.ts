import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  /* config options here */
  output: "standalone", // the minimal self-contained build frontend/Dockerfile's runtime stage copies
  cacheComponents: true,
  partialPrefetching: true,
  experimental: {
    proxyTimeout: 185000,
  },
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
    const backendHost = process.env.INTERNAL_BACKEND_URL || "http://127.0.0.1:8000";
    return {
      afterFiles: [
        {
          source: "/health/:path*",
          destination: `${backendHost}/health/:path*`,
        },
        {
          source: "/api/:path*",
          destination: `${backendHost}/api/:path*`,
        },
        {
          source: "/messages",
          destination: "/inbox",
        },
        {
          source: "/messages/:path*",
          destination: "/inbox/:path*",
        },
      ],
    };
  },
};

export default nextConfig;
