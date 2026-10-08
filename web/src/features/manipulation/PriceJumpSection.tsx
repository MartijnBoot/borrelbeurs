/**
 * ⚡ Price jump (Phase 6 SD23; D-46): a select over the store's active
 * drinks, "Doelprijs (€)" and "Duur (seconden)" (1–1800, default 5). "Start
 * jump" stays disabled until every field parses.
 *
 * With `showBounds` (admin) the target's hint is the drink's `[p_min, p_max]`
 * from `GET config`, which is admin-only; a bar session shows no hint and the
 * server's 422 says when a target is out of bounds.
 */
import { useEffect, useState } from 'react'
import { z } from 'zod'
import { Button } from '../../components/ui/Button'
import { MoneyField } from '../../components/ui/MoneyField'
import { NumberField } from '../../components/ui/NumberField'
import { Select } from '../../components/ui/Select'
import { type FieldValue, formatEuro } from '../../lib/format'
import { HttpError, request } from '../../lib/http'
import { selectActiveDrinks, useExchange } from '../exchange'
import { seconds } from './duration'
import styles from './ManipulationPage.module.css'

const Bounds = z.object({
  drinks: z.array(
    z.object({
      drink_id: z.number().int(),
      p_min_cents: z.number().int(),
      p_max_cents: z.number().int(),
    }),
  ),
})
type Bounds = z.infer<typeof Bounds>['drinks']

/** The drinks' bounds while `enabled`; refetched whenever the store's drinks change. */
function useBounds(enabled: boolean): Bounds {
  const runId = useExchange((s) => s.run?.run_id ?? null)
  const drinks = useExchange((s) => s.drinks)
  const [bounds, setBounds] = useState<Bounds>([])
  useEffect(() => {
    if (!enabled || runId === null) return
    let current = true
    request('GET', `/api/runs/${runId}/config`, { schema: Bounds }).then(
      (config) => current && setBounds(config.drinks),
      () => current && setBounds([]),
    )
    return () => {
      current = false
    }
  }, [enabled, runId, drinks])
  return enabled ? bounds : []
}

export function PriceJumpSection({ showBounds }: { showBounds: boolean }) {
  const drinks = useExchange(selectActiveDrinks)
  const bounds = useBounds(showBounds)
  const [chosen, setChosen] = useState<number | null>(null)
  const [target, setTarget] = useState<FieldValue>(null)
  const [duration, setDuration] = useState<FieldValue>(5)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<string | null>(null)

  // A removed drink leaves the select (SD20): fall back to the first active one.
  const drink = drinks.find((d) => d.drink_id === chosen) ?? drinks[0]
  const durationS = seconds(duration, 1, 1800)
  const range = bounds.find((b) => b.drink_id === drink?.drink_id)
  const ready = drink !== undefined && typeof target === 'number' && durationS !== null

  async function start() {
    if (!ready) return
    setBusy(true)
    try {
      await request('POST', '/api/market/jumps', {
        body: {
          drink_id: drink.drink_id,
          target_price_cents: target,
          duration_ms: durationS * 1000,
        },
        schema: z.unknown(),
      })
      setStatus('Jump gestart')
    } catch (caught) {
      setStatus(
        caught instanceof HttpError && caught.status === 422
          ? 'Doelprijs buiten de grenzen van dit drankje.'
          : 'Starten mislukt. Probeer opnieuw.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className={styles.row}>
        <Select
          label="Drankje"
          value={drink === undefined ? '' : String(drink.drink_id)}
          options={drinks.map((d) => ({ value: String(d.drink_id), label: d.name }))}
          onChange={(value) => setChosen(Number(value))}
        />
        <MoneyField
          label="Doelprijs (€)"
          cents={target}
          onChange={setTarget}
          hint={
            range === undefined
              ? undefined
              : `${formatEuro(range.p_min_cents)} – ${formatEuro(range.p_max_cents)}`
          }
        />
        <NumberField
          label="Duur (seconden)"
          value={duration}
          onChange={setDuration}
          error={durationS === null ? 'Kies 1 tot 1800 seconden.' : undefined}
        />
      </div>
      <div className={styles.row}>
        <Button disabled={busy || !ready} onClick={() => void start()}>
          Start jump
        </Button>
        {status !== null && <span className={styles.muted}>{status}</span>}
      </div>
    </>
  )
}
