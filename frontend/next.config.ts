import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    // GitHub avatars shown on the account settings page.
    remotePatterns: [new URL("https://avatars.githubusercontent.com/**")],
  },
};

export default nextConfig;
