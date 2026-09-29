/**
 * Frontend configuration -- the only module that reads `import.meta.env`.
 *
 * Same rule as `app/core/config.py`, one layer over: everything else takes a
 * value from here rather than reaching into `import.meta.env` itself. Enforced
 * by `web/eslint.config.js`'s `no-restricted-syntax` rule (AC3, web half).
 *
 * There is no server base URL here on purpose -- the SPA is served from the
 * same origin as the API (docs/design/architecture.md:23-25), so every
 * request is a relative path and there is nothing to configure.
 */

export const config = {
  isDev: import.meta.env.DEV,
} as const
