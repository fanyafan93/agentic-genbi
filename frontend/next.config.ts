import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["192.168.101.12"],
  output: "standalone",
};

export default nextConfig;
