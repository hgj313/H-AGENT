/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // 将前端 API 请求代理到后端（避免 CORS 噪音；生产环境建议走同源或网关）
  async rewrites() {
    return [
      {
        source: "/api/proxy/:path*",
        destination: (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000") + "/:path*",
      },
    ];
  },
};

export default nextConfig;
