import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import ru from './ru.json'
import uz from './uz.json'

const STORAGE_KEY = 'crm.lang'

function savedLang(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) ?? 'uz'
  } catch {
    return 'uz'
  }
}

void i18n.use(initReactI18next).init({
  resources: { uz: { translation: uz }, ru: { translation: ru } },
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
