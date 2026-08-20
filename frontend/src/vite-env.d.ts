/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * 'demo' serves browser-local sample data; 'live' talks to the API.
   * Defaults to 'demo' in dev builds and 'live' in production builds.
   */
  readonly VITE_API_MODE?: 'demo' | 'live'
  /** Overrides the API base URL. Defaults to '/api/v1' via the dev proxy. */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
