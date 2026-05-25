package trustlayer

import "os"

// apiTokenEnvVar is the environment fallback for the bearer token
// (ADR-007). Resolution order matches the Python and TypeScript SDKs:
// explicit option > environment > nothing.
const apiTokenEnvVar = "TRUSTLAYER_API_TOKEN"

// resolveAPIToken implements the v0.1 token resolution order.
// An empty string at every level produces an empty result — clients
// MUST treat empty as "no Authorization header" (matches §5.8 default).
func resolveAPIToken(explicit string) string {
	if explicit != "" {
		return explicit
	}
	return os.Getenv(apiTokenEnvVar)
}
