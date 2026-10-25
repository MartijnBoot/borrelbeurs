import { TickMarkType, type UTCTimestamp } from 'lightweight-charts'
import { describe, expect, it } from 'vitest'
import {
  chartTickMark,
  chartTime,
  formatClock,
  formatDayMonthTime,
  formatHourMinute,
  formatWhen,
} from './time'

// 19:30:05 UTC: 21:30:05 in Amsterdam in summer (CEST, +2), 20:30:05 in winter (CET, +1).
const SUMMER_MS = Date.UTC(2026, 9, 18, 19, 30, 5)
const WINTER_MS = Date.UTC(2026, 11, 18, 19, 30, 5)
const seconds = (ms: number) => (ms / 1000) as UTCTimestamp

describe('times are Amsterdam time, whatever zone the machine is in', () => {
  it.each([
    [SUMMER_MS, '21:30:05'],
    [WINTER_MS, '20:30:05'],
  ])('formatClock(%i) is %s', (ms, text) => {
    expect(formatClock(ms)).toBe(text)
  })

  it('formatHourMinute drops the seconds', () => {
    expect(formatHourMinute(SUMMER_MS)).toBe('21:30')
  })

  it('formatWhen shows the date and time', () => {
    expect(formatWhen(SUMMER_MS)).toBe('18-10-2026, 21:30')
  })

  it('formatWhen rolls the date over at Amsterdam midnight, not UTC midnight', () => {
    expect(formatWhen(Date.UTC(2026, 9, 18, 22, 30))).toBe('19-10-2026, 00:30')
  })

  // B-04 SD12: a profile's saved-at, "d mmm HH:mm", the month without a trailing dot.
  it.each([
    [Date.UTC(2026, 9, 24, 12, 5), '24 okt 14:05'],
    [Date.UTC(2026, 2, 3, 13, 5), '3 mrt 14:05'],
    [Date.UTC(2026, 11, 31, 23, 30), '1 jan 00:30'],
  ])('formatDayMonthTime(%i) is %s', (ms, text) => {
    expect(formatDayMonthTime(ms)).toBe(text)
  })
})

describe('chart time axis', () => {
  it.each([
    [TickMarkType.Time, '21:30'],
    [TickMarkType.TimeWithSeconds, '21:30:05'],
    [TickMarkType.DayOfMonth, '18'],
  ])('tick mark type %i is %s', (type, text) => {
    expect(chartTickMark(seconds(SUMMER_MS), type)).toBe(text)
  })

  it('the crosshair label is the clock time', () => {
    expect(chartTime(seconds(WINTER_MS))).toBe('20:30:05')
  })
})
