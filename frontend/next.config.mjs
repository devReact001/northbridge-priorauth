/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  eslint: { ignoreDuringBuilds: true },
  // Only the container build asks for a standalone server (NEXT_OUTPUT=standalone in frontend/Dockerfile). On
  // Windows that mode can fail copying symlinks, so a normal `npm run build` leaves it off.
  ...(process.env.NEXT_OUTPUT === "standalone" ? { output: "standalone" } : {}),
};

export default nextConfig;
