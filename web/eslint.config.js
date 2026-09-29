import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import boundaries from 'eslint-plugin-boundaries'

export default tseslint.config(
  { ignores: ['dist'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
      boundaries,
    },
    settings: {
      // Each feature is a folder under src/features/*; Phase 4's features
      // inherit this element type and its entry-point isolation below. The
      // other src/ folders are declared too: the plugin skips imports made
      // from a file that belongs to no element, so without them src/app --
      // the features' main consumer -- would go unchecked.
      'boundaries/elements': [
        { type: 'features', pattern: 'src/features/*' },
        { type: 'app', pattern: 'src/app' },
        { type: 'lib', pattern: 'src/lib' },
        { type: 'components', pattern: 'src/components' },
        { type: 'api', pattern: 'src/api' },
      ],
      // The plugin's default resolver only tries .js, so an extensionless
      // TypeScript import never resolved and was silently let through.
      'import/resolver': { node: { extensions: ['.ts', '.tsx'] } },
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],
      // Every feature exposes exactly one entry point (index.ts); nothing
      // outside a feature may reach into its internals.
      'boundaries/entry-point': [
        'error',
        {
          default: 'disallow',
          policies: [{ target: { element: { type: 'features' } }, allow: ['index.ts'] }],
        },
      ],
      // AC3 (web half): import.meta.env is read only in src/lib/config.ts —
      // everywhere else must go through that module.
      'no-restricted-syntax': [
        'error',
        {
          selector:
            "MemberExpression[object.type='MetaProperty'][object.meta.name='import'][object.property.name='meta'][property.name='env']",
          message: 'Read env vars only in src/lib/config.ts.',
        },
      ],
    },
  },
  {
    files: ['src/lib/config.ts'],
    rules: {
      'no-restricted-syntax': 'off',
    },
  },
)
