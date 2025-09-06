import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  output: 'export',
  basePath: '/maxicoursesapp',
  images: { unoptimized: true },
  trailingSlash: true
}

export default nextConfig
