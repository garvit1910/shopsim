import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

/** Proxy the engine API through the app's own origin — no CORS anywhere.
 * SIM_API_URL flips to the compose service name in docker (plan 5.7). */
const SIM = process.env.SIM_API_URL ?? "http://127.0.0.1:8000";

/** @type {import('next').NextConfig} */
export default {
  /** A stray package-lock.json in the home directory makes Next infer the
   * workspace root as ~/ and trace the whole home tree. Pin it to this app. */
  outputFileTracingRoot: dirname(fileURLToPath(import.meta.url)),
  async rewrites() {
    return [{ source: "/api/sim/:path*", destination: `${SIM}/:path*` }];
  },
};
