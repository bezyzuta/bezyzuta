import type { NextConfig } from "next";

// Static export for GitHub Pages.
// Repo is bezyzuta/bezyzuta → site served at https://bezyzuta.github.io/bezyzuta/
// so basePath/assetPrefix must include the repo name.
const isProd = process.env.NODE_ENV === "production";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  basePath: isProd ? "/bezyzuta" : "",
  assetPrefix: isProd ? "/bezyzuta/" : "",
};

export default nextConfig;
