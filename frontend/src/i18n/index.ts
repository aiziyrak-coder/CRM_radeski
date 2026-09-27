import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import ru from './ru.json'
import uz from './uz.json'

type Tree = { [key: string]: string | string[] | Tree }

/** Extra per-area files (src/i18n/<area>.uz.json / .ru.json) are deep-merged over the main one,
 * so parallel work on different pages doesn't edit the same big file. */
function merged(base: Tree, lang: 'uz' | 'ru'): Tree {
  const extra = import.meta.glob<{ default: Tree }>('./*.*.json', { eager: true })
  const deep = (a: Tree, b: Tree): Tree => {
    const out: Tree = { ...a }
    for (const [k, v] of Object.entries(b)) {
      const cur = out[k]
      const nested = (x: unknown): x is Tree => typeof x === 'object' && x !== null && !Array.isArray(x)
      out[k] = nested(v) && nested(cur) ? deep(cur, v) : v
    }
    return out
  }
  return Object.entries(extra)
    .filter(([path]) => path.endsWith(`.${lang}.json`))
    .sort(([a], [b]) => a.localeCompare(b))
    .reduce((acc, [, mod]) => deep(acc, mod.default), base)
}

const STORAGE_KEY = 'crm.lang'

function savedLang(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) ?? 'uz'
  } catch {
    return 'uz'
  }
}

void i18n.use(initReactI18next).init({
  resources: { uz: { translation: merged(uz, 'uz') }, ru: { translation: merged(ru, 'ru') } },
  lng: savedLang(),
  fallbackLng: 'uz',
  interpolation: { escapeValue: false },
})

i18n.on('languageChanged', (lng) => {
  document.documentElement.lang = lng
  try {
    localStorage.setItem(STORAGE_KEY, lng)
  } catch {
    // storage unavailable (private mode) — language just won't persist
  }
})

export default i18n
