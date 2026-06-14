/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Allow the embeddable leaderboard widget to be framed by partner sites.
  async headers() {
    return [
      {
        source: "/embed/:path*",
        headers: [{ key: "X-Frame-Options", value: "ALLOWALL" }]
      }
    ];
  }
};

export default nextConfig;
