// Register @testing-library/jest-dom's custom matchers
// (toBeInTheDocument, toHaveTextContent, etc.) with Vitest's expect.
// Loaded by `vitest.config.ts` for every test run; the matchers only
// fire on DOM nodes, so node-environment tests are unaffected.
import "@testing-library/jest-dom/vitest";
