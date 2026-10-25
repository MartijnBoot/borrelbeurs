import { manipulationExplanations } from '../../features/manipulation'
import { settingsExplanations } from '../../features/settings'

/**
 * Every setting's name for a person, by wire name (B-04 PD11): what a 422 naming a
 * field shows (AC23). Built here because `features/settings` may not import
 * `features/manipulation`, where the four idle settings are explained.
 */
export const settingNames: Readonly<Record<string, string>> = Object.fromEntries(
  Object.entries({ ...settingsExplanations, ...manipulationExplanations }).map(([wire, entry]) => [
    wire,
    entry.name,
  ]),
)
