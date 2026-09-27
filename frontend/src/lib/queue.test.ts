import { describe, expect, it } from 'vitest'
import {
  conversion,
  fillScript,
  priorityLevel,
  slaMinutesLeft,
  suggestedResult,
  taskScriptValues,
} from './ops'
import { ageOf } from './patients'

const context = {
  doctor_uz: 'Doktor B',
  doctor_ru: 'Доктор Б',
  services_uz: 'Konsultatsiya',
  services_ru: 'Консультация',
  branch_uz: "Farg'ona",
  branch_ru: 'Фергана',
}

describe('script placeholders come from the task (TZ 4.6)', () => {
  const task = { appointment_at: '2026-09-28T04:30:00Z', context }

  it('fills doctor, service, branch, date and time in the script language', () => {
    const uz = taskScriptValues(task, 'uz', { Ism: 'Aziza' })
    expect(fillScript('[Ism]: [sana] [vaqt] da [shifokor], [xizmat], [filial]', uz)).toBe(
      "Aziza: 28.09.2026 09:30 da Doktor B, Konsultatsiya, Farg'ona",
    )
    const ru = taskScriptValues(task, 'ru')
    expect(fillScript('[shifokor] / [xizmat] / [filial]', ru)).toBe('Доктор Б / Консультация / Фергана')
  })

  it('leaves unknown placeholders visible for the operator', () => {
    const values = taskScriptValues({ appointment_at: null, context: undefined }, 'uz')
    expect(fillScript('[shifokor] [sana] [1-vaqt]', values)).toBe('[shifokor] [sana] [1-vaqt]')
  })

  it('falls back to the other language when a name exists in one only', () => {
    const values = taskScriptValues({ appointment_at: null, context: { ...context, doctor_ru: null } }, 'ru')
    expect(values.shifokor).toBe('Doktor B')
  })
})

describe('lead funnel and SLA helpers', () => {
  it('conversion is a whole percent, null without a base', () => {
    expect(conversion(3, 2)).toBe(67)
    expect(conversion(0, 0)).toBeNull()
    expect(conversion(undefined, 1)).toBeNull()
  })

  it('minutes left until the SLA deadline, negative once late', () => {
    const now = Date.parse('2026-09-28T05:00:00Z')
    expect(slaMinutesLeft('2026-09-28T05:12:30Z', now)).toBe(12)
    expect(slaMinutesLeft('2026-09-28T04:30:00Z', now)).toBe(-30)
  })
})

describe('patient and task helpers', () => {
  it('age in full years on a given day', () => {
    expect(ageOf('1990-09-28', '2026-09-28')).toBe(36)
    expect(ageOf('1990-09-29', '2026-09-28')).toBe(35)
    expect(ageOf(null)).toBeNull()
  })

  it('named priority levels', () => {
    expect(priorityLevel(4)).toBe('urgent')
    expect(priorityLevel(8)).toBe('high')
    expect(priorityLevel(20)).toBe('normal')
    expect(priorityLevel(45)).toBe('low')
  })

  it('the AI suggestion prefills the result only with an outcome allowed for the task', () => {
    const ai = { analysis_id: 'a', call_id: 'c', reason: 'price', summary: 'Qimmat', next_step: null }
    expect(suggestedResult({ type: 'new_lead', ai_suggestion: { ...ai, outcome: 'refused' } }).outcome).toBe(
      'refused',
    )
    // "confirmed" is not a new-lead result: the form starts from the task's first option
    expect(
      suggestedResult({ type: 'new_lead', ai_suggestion: { ...ai, outcome: 'confirmed' } }).outcome,
    ).toBe('thinking')
  })
})
