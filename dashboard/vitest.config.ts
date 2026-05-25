import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

/**
 * Vitest configuration for the dashboard.
 *
 * - `@vitejs/plugin-react` so test files can render JSX from `*.tsx`.
 * - `setupFiles` loads the jest-dom matchers so `toBeInTheDocument()`
 *   and friends are available to component tests.
 * - The environment is *not* pinned globally — `api.test.ts` runs in
 *   node (faster), and component tests use the `// @vitest-environment
 *   jsdom` per-file directive.
 */
export default defineConfig({
  plugins: [react()],
  test: {
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
