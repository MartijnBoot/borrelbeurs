// The settings feature's public surface (Phase 6 PD13): the layout and every
// section `/settings` composes. The keys section lives in `features/keys`,
// composed by `app/pages/SettingsPage.tsx`.
export { BorrelSection } from './BorrelSection'
export { DemandSection } from './DemandSection'
export { BoundsSection } from './BoundsSection'
export { DrinksSection } from './DrinksSection'
// The 29 settings explanations (B-01's 21, B-03's six, B-06's two), for the
// page-level checks (B-01 AC9, AC10).
export { default as settingsExplanations } from './explanations.json'
export { GlobalSection } from './GlobalSection'
export { ImagesSection } from './ImagesSection'
export { ProfilesSection } from './ProfilesSection'
export { type SettingsSection, SettingsLayout } from './SettingsLayout'
export { SystemSection } from './SystemSection'
export { ThemeEditor } from './ThemeEditor'
export { ThemeSection } from './ThemeSection'
export { type CurrentRun, useCurrentRun } from './useCurrentRun'
