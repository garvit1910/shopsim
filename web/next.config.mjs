/** Proxy the engine API through the app's own origin — no CORS anywhere.
 * SIM_API_URL flips to the compose service name in docker (plan 5.7). */
const SIM = process.env.SIM_API_URL ?? "http://127.0.0.1:8000";

/** @type {import('next').NextConfig} */
export default {
  async rewrites() {
    return [{ source: "/api/sim/:path*", destination: `${SIM}/:path*` }];
  },
};
