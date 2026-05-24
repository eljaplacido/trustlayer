/**
 * Bearer-token resolution shared by every TrustLayer client (ADR-007).
 *
 * Resolution order:
 *   1. Explicit `apiKey` passed to the client constructor (wins).
 *   2. `TRUSTLAYER_API_TOKEN` from Node's `process.env` (server / CLI use).
 *   3. `VITE_TRUSTLAYER_API_TOKEN` from `import.meta.env` (dashboard / Vite use).
 *   4. Undefined — clients send no Authorization header.
 *
 * Returning `undefined` is intentional: the client's `headers()` checks
 * truthiness before adding the header, so an unset token produces an
 * un-authenticated request, exactly matching the Python SDK.
 */

const ENV_VAR = "TRUSTLAYER_API_TOKEN";
const VITE_ENV_VAR = "VITE_TRUSTLAYER_API_TOKEN";

function fromProcessEnv(): string | undefined {
  if (typeof process === "undefined") return undefined;
  const env = (process as { env?: Record<string, string | undefined> }).env;
  const raw = env?.[ENV_VAR];
  return raw && raw.length > 0 ? raw : undefined;
}

function fromImportMetaEnv(): string | undefined {
  // `import.meta.env` is injected by Vite at build time. Guarded so the
  // SDK still tree-shakes cleanly under Node + bare ESM.
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const meta = (import.meta as any)?.env as
      | Record<string, string | undefined>
      | undefined;
    const raw = meta?.[VITE_ENV_VAR];
    return raw && raw.length > 0 ? raw : undefined;
  } catch {
    return undefined;
  }
}

export function resolveApiToken(explicit: string | undefined): string | undefined {
  if (explicit !== undefined) return explicit;
  return fromProcessEnv() ?? fromImportMetaEnv();
}
