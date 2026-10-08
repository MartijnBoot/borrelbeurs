import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import boundaries from 'eslint-plugin-boundaries'

// AC32 (D-25): user text is only ever a text node -- no HTML sink anywhere in
// the bundle. Shared with the src/lib/config.ts override below, which lifts
// only the import.meta.env ban.
const htmlSinks = [
  {
    selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
    message: 'Render user text as a text node, never as HTML.',
  },
  {
    selector:
      'AssignmentExpression > MemberExpression.left[property.name=/^(innerHTML|outerHTML)$/]',
    message: 'Render user text as a text node, never as HTML.',
  },
  {
    selector: "CallExpression > MemberExpression.callee[property.name='insertAdjacentHTML']",
    message: 'Render user text as a text node, never as HTML.',
  },
]

// AC3 (web half): import.meta.env is read only in src/lib/config.ts —
// everywhere else must go through that module.
const envRead = {
  selector:
    "MemberExpression[object.type='MetaProperty'][object.meta.name='import'][object.property.name='meta'][property.name='env']",
  message: 'Read env vars only in src/lib/config.ts.',
}

// Phase 5 AC17 (PD16): revenue and quantities come only from the server's
// `snapshot.earnings` and `order.earnings_delta`. Nothing in the bundle
// multiplies by a quantity -- v1's `computeLocalEarnings` shape
// (bar.html:200-205). Tests and e2e specs are exempt (override below): they
// compute expected values.
const revenueMessage =
  'Revenue comes from the server (earnings, earnings_delta), never price × quantity (AC17).'
const revenueArithmetic = [
  { selector: "Identifier[name='computeLocalEarnings']", message: revenueMessage },
  {
    selector: "BinaryExpression[operator='*'] > Identifier[name=/qty|quantity/i]",
    message: revenueMessage,
  },
  {
    selector: "BinaryExpression[operator='*'] > MemberExpression[property.name=/qty|quantity/i]",
    message: revenueMessage,
  },
]

// Phase 6 SD27 (PD16, D-03): a form value is never coerced with `+x`, which
// turns "" into 0. Parse it (NumberField, MoneyField, parseEuroCents). Every
// unary + in non-test source, whatever it is named. Tests are exempt.
const unaryPlus = {
  selector: "UnaryExpression[operator='+']",
  message: 'Parse form values (NumberField, parseEuroCents); `+x` turns "" into 0 (SD27).',
}

// Phase 6 AC39 (PD16): destructive actions confirm with ConfirmDialog, never the
// browser's own dialogs.
const dialogMessage = 'Use ConfirmDialog or Toast, never a native dialog (AC39).'

// AC12 (D-14): nothing in the bundle persists to web storage; the theme and
// every other setting live on the server.
const storageMessage = 'Web storage is banned; state lives on the server.'

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
        { type: 'features', pattern: 'src/features/*', capture: ['feature'] },
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
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      // Every feature exposes exactly one entry point (index.ts); nothing
      // outside a feature may reach into its internals. The shared folders
      // (lib, components, api, app) have no single entry point: any of their
      // files may be imported. Without that second policy `default:
      // 'disallow'` refused every import of lib/ or components/.
      'boundaries/entry-point': [
        'error',
        {
          default: 'disallow',
          policies: [
            { target: { element: { type: 'features' } }, allow: ['index.ts'] },
            { target: { element: { type: '!features' } }, allow: ['**'] },
          ],
        },
      ],
      // SD27: features are sibling-isolated. exchange is the shared one --
      // it imports no feature, and the others import only exchange among
      // features. The last matching policy wins, so the allow refines the
      // blanket disallow. (`element-types` is this rule's deprecated name.)
      'boundaries/dependencies': [
        'error',
        {
          default: 'allow',
          policies: [
            {
              from: { element: { type: 'features' } },
              disallow: { to: { element: { type: 'features' } } },
            },
            {
              from: { element: { type: 'features', captured: { feature: '!exchange' } } },
              allow: { to: { element: { type: 'features', captured: { feature: 'exchange' } } } },
            },
          ],
        },
      ],
      'no-restricted-syntax': ['error', envRead, ...htmlSinks, ...revenueArithmetic, unaryPlus],
      'no-restricted-globals': [
        'error',
        { name: 'localStorage', message: storageMessage },
        { name: 'sessionStorage', message: storageMessage },
        { name: 'confirm', message: dialogMessage },
        { name: 'alert', message: dialogMessage },
        { name: 'prompt', message: dialogMessage },
      ],
      'no-restricted-properties': [
        'error',
        { object: 'window', property: 'localStorage', message: storageMessage },
        { object: 'window', property: 'sessionStorage', message: storageMessage },
        { object: 'window', property: 'confirm', message: dialogMessage },
        { object: 'window', property: 'alert', message: dialogMessage },
        { object: 'window', property: 'prompt', message: dialogMessage },
      ],
    },
  },
  {
    files: ['src/lib/config.ts'],
    rules: {
      'no-restricted-syntax': ['error', ...htmlSinks, ...revenueArithmetic, unaryPlus],
    },
  },
  {
    files: ['**/*.test.{ts,tsx}', 'e2e/**'],
    rules: {
      'no-restricted-syntax': ['error', envRead, ...htmlSinks],
    },
  },
)
