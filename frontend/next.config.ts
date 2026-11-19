import type { NextConfig } from "next";

// Server-side only: where the Next.js server forwards /api/* and /health/* requests.
// Never expose this with a NEXT_PUBLIC_ prefix. It's read when the config loads
// (`next dev` start or `next build`), so Docker passes it as a build argument.
const backendUrl = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  // Dev-only badge: keep it clear of the sidebar's bottom-left buttons
  devIndicators: { position: "bottom-right" },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backendUrl}/api/:path*` },
      { source: "/health", destination: `${backendUrl}/health` },
      { source: "/health/:path*", destination: `${backendUrl}/health/:path*` },
    ];
  },
};

export default nextConfig;
