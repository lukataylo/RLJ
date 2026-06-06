/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_ORCHESTRATOR_URL?: string;
  readonly VITE_MAPBOX_TOKEN?: string;
  readonly VITE_LOCAL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
