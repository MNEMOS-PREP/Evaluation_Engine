/// <reference types="vite/client" />

/**
 * Global env typing for this app.
 *
 * `@ai/core` ships TypeScript source rather than a build, so tsc checks its
 * files too — the augmentation has to be global, declared by the app that
 * consumes it, not scoped inside the package.
 */

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
