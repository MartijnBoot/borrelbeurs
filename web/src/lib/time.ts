/**
 * The one place times are formatted for a person: always Amsterdam time.
 *
 * Without an explicit zone, Intl uses the browser machine's zone, and
 * lightweight-charts draws its `UTCTimestamp` axis in UTC. Both are wrong on a
 * laptop whose zone was never set, and the charts were always wrong.
 */
import { type Time, TickMarkType } from 'lightweight-charts'

export const TIME_ZONE = 'Europe/Amsterdam'

const formatter = (options: Intl.DateTimeFormatOptions) =>
  new Intl.DateTimeFormat('nl-NL', { timeZone: TIME_ZONE, ...options })

const CLOCK = formatter({ hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
const HOUR_MINUTE = formatter({ hour: '2-digit', minute: '2-digit', hour12: false })
const WHEN = formatter({ dateStyle: 'short', timeStyle: 'short' })
const DAY = formatter({ day: 'numeric' })
const MONTH = formatter({ month: 'short' })
const YEAR = formatter({ year: 'numeric' })

/** `HH:MM:SS`. */
export const formatClock = (ms: number) => CLOCK.format(ms)

/** `HH:MM`. */
export const formatHourMinute = (ms: number) => HOUR_MINUTE.format(ms)

/** `dd-mm-yyyy, HH:MM`. */
export const formatWhen = (ms: number) => WHEN.format(ms)

/** Chart times are `UTCTimestamp`s: whole seconds since the epoch. */
const chartMs = (time: Time) => Number(time) * 1000

const TICK: Readonly<Record<TickMarkType, Intl.DateTimeFormat>> = {
  [TickMarkType.Year]: YEAR,
  [TickMarkType.Month]: MONTH,
  [TickMarkType.DayOfMonth]: DAY,
  [TickMarkType.Time]: HOUR_MINUTE,
  [TickMarkType.TimeWithSeconds]: CLOCK,
}

/** The time axis's tick labels (`timeScale.tickMarkFormatter`). */
export const chartTickMark = (time: Time, type: TickMarkType) => TICK[type].format(chartMs(time))

/** The crosshair's time label (`localization.timeFormatter`). */
export const chartTime = (time: Time) => formatClock(chartMs(time))
