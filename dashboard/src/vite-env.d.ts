/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_TRUSTLAYER_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
