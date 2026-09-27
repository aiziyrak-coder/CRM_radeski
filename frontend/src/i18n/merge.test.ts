import { describe, expect, it } from 'vitest'
import i18n from './index'

describe('per-area translation files', () => {
  it('are merged over the main file', () => {
    expect(i18n.t('app.i18nProbe', { lng: 'uz' })).toBe('ok')
    expect(i18n.t('app.title', { lng: 'uz' })).not.toBe('app.title') // the main file is kept
  })
})
