import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  typescript: {
    tsconfigPath: "tsconfig.check.json",
  },
};

export default nextConfig;
