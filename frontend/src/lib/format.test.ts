import { describe, expect, it } from 'vitest'
import { canOpen } from './navigation'
import { fillScript } from './ops'
import { formatDate, formatDateTime, formatPhone } from './patients'
import { clinicDate } from './scheduling'
import { dialable, formatDuration } from './telephony'

describe('dates are shown in the clinic time zone (Asia/Tashkent, UTC+5)', () => {
  it('a plain date is not shifted', () => {
    expect(formatDate('1985-04-12')).toBe('12.04.1985')
  })
  it('a timestamp late in the UTC evening is already the next clinic day', () => {
    expect(formatDate('2026-09-26T20:30:00Z')).toBe('27.09.2026')
    expect(formatDateTime('2026-09-26T20:30:00Z')).toBe('27.09.2026 01:30')
    expect(clinicDate('2026-09-26T20:30:00Z')).toBe('2026-09-27')
  })
  it('missing values show a dash', () => {
    expect(formatDate(null)).toBe('—')
    expect(formatDateTime(null)).toBe('—')
  })
})

describe('phones', () => {
  it('formats E.164 Uzbek numbers for display', () => {
    expect(formatPhone('+998900001122')).toBe('+998 90 000-11-22')
    expect(formatPhone('+74951234567')).toBe('+74951234567') // foreign: as is
    expect(formatPhone(null)).toBe('')
  })
  it('turns whatever was typed into the 9 digits the PBX dials', () => {
    expect(dialable('+998 90 000-11-22')).toBe('900001122')
    expect(dialable('998900001122')).toBe('900001122')
    expect(dialable('8 90 000 11 22')).toBe('900001122')
    expect(dialable('90-000-11-22')).toBe('900001122')
  })
})

describe('call durations', () => {
  it('shows minutes and seconds', () => {
    expect(formatDuration(125)).toBe('2:05')
    expect(formatDuration(0)).toBe('0:00')
    expect(formatDuration(null)).toBe('—')
  })
})

describe('scripts', () => {
  it('fills known placeholders and keeps unknown ones visible', () => {
    const body = 'Assalomu alaykum, [Bemor]! Men [Ism]. Qabul [sana] kuni.'
    expect(fillScript(body, { Bemor: 'Aziza', Ism: 'Dilnoza', sana: undefined })).toBe(
      'Assalomu alaykum, Aziza! Men Dilnoza. Qabul [sana] kuni.',
    )
  })
})

describe('role access mirrors the backend', () => {
  it('owner sees calls and QA but not the patient base or inquiries', () => {
    expect(canOpen('owner', '/calls')).toBe(true)
    expect(canOpen('owner', '/qa')).toBe(true)
    expect(canOpen('owner', '/patients')).toBe(false)
    expect(canOpen('owner', '/leads')).toBe(false)
  })
  it('operators work tasks but do not manage users', () => {
    expect(canOpen('operator', '/tasks')).toBe(true)
    expect(canOpen('operator', '/users')).toBe(false)
    expect(canOpen(undefined, '/tasks')).toBe(false)
  })
})
