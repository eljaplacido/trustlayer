/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_TRUSTLAYER_BASE_URL?: string;
  readonly VITE_TRUSTLAYER_API_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
