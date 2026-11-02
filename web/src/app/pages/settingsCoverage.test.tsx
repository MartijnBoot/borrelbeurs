// @vitest-environment jsdom
// AC10, AC11 (B-12 PD16): every control of the old one-page `/settings` is on
// exactly one of the three screens, with the same label, and the setting names
// and explanations are byte for byte as on `main`.
//
// `OLD_CONTROLS` is the old page's list, captured from it at B-12 T5 with the
// fixture in `settingsFixture.ts` (the page itself is gone since T6): per control its old section, its role (a checkbox and a
// switch both count as `toggle`) and its accessible name, in page order. It
// carries the section because one label, "Opslaan", sits in sections that land
// on two screens: the section pins every control, that one included, to one
// screen. The section navigation, its select and "← Instellingen" are left out.
// A control that renders only on a draft run (R7) is not in the fixture; its
// section's own test covers it.
//
// The test maps each old section to its screen, moves the controls B-12 moves
// to another screen (`MOVED`), adds the controls B-12 adds (`ADDED`), and
// asserts each screen holds exactly that list.
import { act, cleanup, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import explanationsText from '../../features/settings/explanations.json?raw'
import { renderInDataRouter } from '../testRouter'
import { stubNarrow, stubServer } from './settingsFixture'
import { BeheerPage, SpelopzetPage, WalletsScreenPage } from './SettingsScreens'

type Control = readonly [section: string, role: string, name: string]

// prettier-ignore
const OLD_CONTROLS: readonly Control[] = [
  ['borrel', 'button', 'Borrel afsluiten'],
  ['systeem', 'button', 'Evenwicht op huidige prijzen'],
  ['systeem', 'button', 'Uitleg: Evenwicht op huidige prijzen'],
  ['systeem', 'button', 'Sluit app'],
  ['globaal', 'button', 'Uitleg: Prijsstap (€)'],
  ['globaal', 'textbox', 'Prijsstap (€)'],
  ['globaal', 'button', 'Uitleg: Beweging per bestelling'],
  ['globaal', 'textbox', 'Beweging per bestelling'],
  ['globaal', 'button', 'Uitleg: Drukdrempel'],
  ['globaal', 'textbox', 'Drukdrempel'],
  ['globaal', 'button', 'Uitleg: Concurrentie tussen drankjes'],
  ['globaal', 'textbox', 'Concurrentie tussen drankjes'],
  ['globaal', 'button', 'Uitleg: Trek naar gemiddelde prijs'],
  ['globaal', 'textbox', 'Trek naar gemiddelde prijs'],
  ['globaal', 'button', 'Uitleg: Nawerking van bestellingen'],
  ['globaal', 'textbox', 'Nawerking van bestellingen'],
  ['globaal', 'button', 'Uitleg: Geheugen van bestellingen'],
  ['globaal', 'textbox', 'Geheugen van bestellingen'],
  ['globaal', 'button', 'Uitleg: Grafiekgeschiedenis (min)'],
  ['globaal', 'textbox', 'Grafiekgeschiedenis (min)'],
  ['globaal', 'button', 'Uitleg: Ritme stille drankjes (min)'],
  ['globaal', 'textbox', 'Ritme stille drankjes (min)'],
  ['globaal', 'button', 'Uitleg: Kaarsbreedte (sec)'],
  ['globaal', 'textbox', 'Kaarsbreedte (sec)'],
  ['globaal', 'button', 'Uitleg: Willekeurige ruis'],
  ['globaal', 'toggle', 'Willekeurige ruis'],
  ['globaal', 'button', 'Uitleg: Sterkte ruis'],
  ['globaal', 'textbox', 'Sterkte ruis'],
  ['globaal', 'button', 'Uitleg: Ritme ruis (min)'],
  ['globaal', 'textbox', 'Ritme ruis (min)'],
  ['globaal', 'button', 'Uitleg: Extra ruis bij drukte'],
  ['globaal', 'textbox', 'Extra ruis bij drukte'],
  ['globaal', 'button', 'Uitleg: Reactiesnelheid drukte'],
  ['globaal', 'textbox', 'Reactiesnelheid drukte'],
  ['globaal', 'button', 'Uitleg: Grens ruis'],
  ['globaal', 'textbox', 'Grens ruis'],
  ['globaal', 'button', 'Uitleg: Wallet verplicht'],
  ['globaal', 'toggle', 'Wallet verplicht'],
  ['globaal', 'button', 'Uitleg: Rood staan tot (€)'],
  ['globaal', 'textbox', 'Rood staan tot (€)'],
  ['globaal', 'button', 'Opslaan instellingen'],
  ['profielen', 'textbox', 'Naam'],
  ['profielen', 'button', 'Opslaan als profiel'],
  ['kleuren', 'button', 'Oud Geld'],
  ['kleuren', 'button', 'Blauw'],
  ['kleuren', 'button', 'Groen'],
  ['kleuren', 'button', 'Paars'],
  ['kleuren', 'button', 'Rood'],
  ['kleuren', 'button', 'Eigen'],
  ['afbeeldingen', 'h3', 'Achtergrond'],
  ['afbeeldingen', 'h3', 'Header'],
  ['afbeeldingen', 'h3', 'Logo'],
  ['afbeeldingen', 'h3', 'Promotie tegel'],
  ['drankjes', 'h3', 'Drankje toevoegen'],
  ['drankjes', 'textbox', 'Naam'],
  ['drankjes', 'button', 'Uitleg: Minimumprijs (€)'],
  ['drankjes', 'textbox', 'Minimumprijs (€)'],
  ['drankjes', 'button', 'Uitleg: Startprijs (€)'],
  ['drankjes', 'textbox', 'Startprijs (€)'],
  ['drankjes', 'button', 'Uitleg: Maximumprijs (€)'],
  ['drankjes', 'textbox', 'Maximumprijs (€)'],
  ['drankjes', 'button', 'Uitleg: Normale barprijs (€)'],
  ['drankjes', 'textbox', 'Normale barprijs (€)'],
  ['drankjes', 'button', 'Uitleg: Basisvraag (a)'],
  ['drankjes', 'textbox', 'Basisvraag (a)'],
  ['drankjes', 'button', 'Uitleg: Prijsgevoeligheid (d)'],
  ['drankjes', 'textbox', 'Prijsgevoeligheid (d)'],
  ['drankjes', 'button', 'Uitleg: Vraagverschuiving (s0)'],
  ['drankjes', 'textbox', 'Vraagverschuiving (s0)'],
  ['drankjes', 'button', 'Uitleg: Voordeel onder gemiddelde (c)'],
  ['drankjes', 'textbox', 'Voordeel onder gemiddelde (c)'],
  ['drankjes', 'button', 'Toevoegen'],
  ['drankjes', 'h3', 'Bier'],
  ['drankjes', 'textbox', 'Naam'],
  ['drankjes', 'button', 'Uitleg: Normale barprijs (€)'],
  ['drankjes', 'textbox', 'Normale barprijs (€)'],
  ['drankjes', 'button', 'Opslaan'],
  ['drankjes', 'button', 'Verwijderen'],
  ['drankjes', 'h3', 'Wijn'],
  ['drankjes', 'textbox', 'Naam'],
  ['drankjes', 'button', 'Uitleg: Normale barprijs (€)'],
  ['drankjes', 'textbox', 'Normale barprijs (€)'],
  ['drankjes', 'button', 'Opslaan'],
  ['drankjes', 'button', 'Verwijderen'],
  ['prijzen', 'h3', 'Bier'],
  ['prijzen', 'button', 'Uitleg: Minimumprijs (€)'],
  ['prijzen', 'textbox', 'Minimumprijs (€)'],
  ['prijzen', 'button', 'Uitleg: Startprijs (€)'],
  ['prijzen', 'textbox', 'Startprijs (€)'],
  ['prijzen', 'button', 'Uitleg: Maximumprijs (€)'],
  ['prijzen', 'textbox', 'Maximumprijs (€)'],
  ['prijzen', 'button', 'Opslaan'],
  ['prijzen', 'h3', 'Wijn'],
  ['prijzen', 'button', 'Uitleg: Minimumprijs (€)'],
  ['prijzen', 'textbox', 'Minimumprijs (€)'],
  ['prijzen', 'button', 'Uitleg: Startprijs (€)'],
  ['prijzen', 'textbox', 'Startprijs (€)'],
  ['prijzen', 'button', 'Uitleg: Maximumprijs (€)'],
  ['prijzen', 'textbox', 'Maximumprijs (€)'],
  ['prijzen', 'button', 'Opslaan'],
  ['vraag', 'button', 'Uitleg: Verwachte verkoop meetellen'],
  ['vraag', 'toggle', 'Verwachte verkoop meetellen'],
  ['vraag', 'button', 'Uitleg: Evenwicht zetten bij live zetten'],
  ['vraag', 'toggle', 'Evenwicht zetten bij live zetten'],
  ['vraag', 'button', 'Opslaan schakelaars'],
  ['vraag', 'table', 'Coëfficiënten'],
  ['vraag', 'button', 'Uitleg: Basisvraag (a)'],
  ['vraag', 'button', 'Uitleg: Prijsgevoeligheid (d)'],
  ['vraag', 'button', 'Uitleg: Vraagverschuiving (s0)'],
  ['vraag', 'button', 'Uitleg: Voordeel onder gemiddelde (c)'],
  ['vraag', 'textbox', 'Bier Basisvraag (a)'],
  ['vraag', 'textbox', 'Bier Prijsgevoeligheid (d)'],
  ['vraag', 'textbox', 'Bier Vraagverschuiving (s0)'],
  ['vraag', 'textbox', 'Bier Voordeel onder gemiddelde (c)'],
  ['vraag', 'textbox', 'Wijn Basisvraag (a)'],
  ['vraag', 'textbox', 'Wijn Prijsgevoeligheid (d)'],
  ['vraag', 'textbox', 'Wijn Vraagverschuiving (s0)'],
  ['vraag', 'textbox', 'Wijn Voordeel onder gemiddelde (c)'],
  ['vraag', 'button', 'Opslaan coëfficiënten'],
  ['sleutels', 'table', ''],
  ['sleutels', 'button', 'Intrekken'],
  ['sleutels', 'combobox', 'Rol'],
  ['sleutels', 'textbox', 'Label'],
  ['sleutels', 'button', 'Nieuwe sleutel'],
  ['wallets', 'h3', 'Aanmeldcode'],
  ['wallets', 'textbox', 'Aanmeldcode'],
  ['wallets', 'button', 'Opslaan'],
  ['wallets', 'button', 'Wissen'],
  ['wallets', 'toggle', 'QR-code op het scherm'],
  ['wallets', 'h3', 'Bewaartermijnen'],
  ['wallets', 'spinbutton', 'Zonder opwaardering verwijderen na (dagen)'],
  ['wallets', 'spinbutton', 'Inactief verwijderen na (maanden)'],
  ['wallets', 'button', 'Opslaan'],
  ['wallets', 'h3', 'Totalen'],
  ['wallets', 'h3', 'Alle wallets'],
]

type ScreenName = 'Spelopzet' | 'Mensen en wallets' | 'Beheer'

/** Where each old section went (SD3). */
const SCREEN_OF: Readonly<Record<string, ScreenName>> = {
  borrel: 'Spelopzet',
  profielen: 'Spelopzet',
  drankjes: 'Spelopzet',
  prijzen: 'Spelopzet',
  vraag: 'Spelopzet',
  kleuren: 'Spelopzet',
  afbeeldingen: 'Spelopzet',
  wallets: 'Mensen en wallets',
  globaal: 'Beheer',
  sleutels: 'Beheer',
  systeem: 'Beheer',
}

/** Controls that leave their old section's screen: `section role name` to its new screen. */
const MOVED: Readonly<Record<string, ScreenName>> = {
  // T7, SD4: Prijsstap to Spelopzet's Prijzen.
  'globaal button Uitleg: Prijsstap (€)': 'Spelopzet',
  'globaal textbox Prijsstap (€)': 'Spelopzet',
  // T8, SD3: Wallet verplicht and Rood staan tot to Betalen.
  'globaal button Uitleg: Wallet verplicht': 'Mensen en wallets',
  'globaal toggle Wallet verplicht': 'Mensen en wallets',
  'globaal button Uitleg: Rood staan tot (€)': 'Mensen en wallets',
  'globaal textbox Rood staan tot (€)': 'Mensen en wallets',
  // T10, SD3: Vraag/Aanbod's switches to Beheer; its table stays on Spelopzet.
  'vraag button Uitleg: Verwachte verkoop meetellen': 'Beheer',
  'vraag toggle Verwachte verkoop meetellen': 'Beheer',
  'vraag button Uitleg: Evenwicht zetten bij live zetten': 'Beheer',
  'vraag toggle Evenwicht zetten bij live zetten': 'Beheer',
  'vraag button Opslaan schakelaars': 'Beheer',
}

/** What B-12 adds, per screen, as `role name`. */
const ADDED: Readonly<Record<ScreenName, readonly string[]>> = {
  Spelopzet: ['button Opslaan prijsstap'], // T7, PD9: Prijsstap's own form
  'Mensen en wallets': ['button Opslaan'], // T8, PD10: Betalen's own form
  // T9, PD11: Globale instellingen' three group headings.
  Beheer: ['h3 Hoe bestellingen de prijs bewegen', 'h3 Willekeurige ruis', 'h3 Koersbord'],
}

const SCREENS: Readonly<Record<ScreenName, React.JSX.Element>> = {
  Spelopzet: <SpelopzetPage />,
  'Mensen en wallets': <WalletsScreenPage />,
  Beheer: <BeheerPage />,
}

const ROLES = ['textbox', 'spinbutton', 'combobox', 'switch', 'checkbox', 'button', 'table']

/** The controls inside a section, in page order, as [role, name]. */
function controlsOf(section: HTMLElement): [string, string][] {
  const found: [Element, string, string][] = []
  const collect = (role: string) => (name: string, element: Element) => {
    found.push([element, role === 'switch' || role === 'checkbox' ? 'toggle' : role, name])
    return true
  }
  for (const role of ROLES) within(section).queryAllByRole(role, { name: collect(role) })
  within(section).queryAllByRole('heading', { level: 3, name: collect('h3') })
  found.sort(([a], [b]) =>
    a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1,
  )
  return found.map(([, role, name]) => [role, name])
}

/** The page's settings sections: the regions that carry an anchor id. */
const sections = () => screen.getAllByRole('region').filter((region) => region.id !== '')

async function settle() {
  for (let i = 0; i < 6; i += 1) await act(async () => {})
}

const key = ([section, role, name]: Control) => `${section} ${role} ${name}`
const sorted = (list: readonly string[]) => [...list].sort()

function expected(screenName: ScreenName): string[] {
  const kept = OLD_CONTROLS.filter(
    (control) => (MOVED[key(control)] ?? SCREEN_OF[control[0]]) === screenName,
  ).map(([, role, name]) => `${role} ${name}`)
  return [...kept, ...ADDED[screenName]]
}

beforeEach(() => {
  stubNarrow(false)
  stubServer()
})

afterEach(cleanup)

describe('the three screens (AC10)', () => {
  it('every old section has a screen, and every move names an old control', () => {
    expect(new Set(OLD_CONTROLS.map(([section]) => section))).toEqual(
      new Set(Object.keys(SCREEN_OF)),
    )
    const old = new Set(OLD_CONTROLS.map(key))
    expect(Object.keys(MOVED).filter((moved) => !old.has(moved))).toEqual([])
  })

  it.each(Object.keys(SCREENS) as ScreenName[])(
    '%s holds its old controls and its additions, nothing else',
    async (screenName) => {
      renderInDataRouter(SCREENS[screenName])
      await settle()
      const shown = sections().flatMap((section) =>
        controlsOf(section).map(([role, name]) => `${role} ${name}`),
      )
      expect(sorted(shown)).toEqual(sorted(expected(screenName)))
    },
  )

  it('joined, the screens hold every old control once, plus the additions', () => {
    const joined = (Object.keys(SCREENS) as ScreenName[]).flatMap(expected)
    const old = OLD_CONTROLS.map(([, role, name]) => `${role} ${name}`)
    const added = Object.values(ADDED).flat()
    expect(sorted(joined)).toEqual(sorted([...old, ...added]))
  })

  it.each(Object.keys(SCREENS) as ScreenName[])(
    '%s: each (i) sits in the section of the control it explains (AC11)',
    async (screenName) => {
      renderInDataRouter(SCREENS[screenName])
      await settle()
      for (const section of sections()) {
        for (const button of within(section).queryAllByRole('button', { name: /^Uitleg: / })) {
          const name = button.getAttribute('aria-label')!.slice('Uitleg: '.length)
          const explained = [
            ...ROLES.flatMap((role) => within(section).queryAllByRole(role, { name })),
            ...within(section).queryAllByRole('columnheader', { name }),
          ]
          expect([name, explained.length > 0]).toEqual([name, true])
        }
      }
    },
  )
})

describe('the setting names and explanations (AC11)', () => {
  it('explanations.json is byte for byte as on main at e1da324', async () => {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(explanationsText))
    const hex = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0'))
    expect(hex.join('')).toBe('40f07406c419a99e2a8fc66d1080fb28aae036274c4010557c45cb3b546e0515')
  })
})
