import { useTranslation } from 'react-i18next'
import { UNKNOWN_NAME } from '../lib/patients'

/** Imported records without a name get a placeholder; show it as such, not as a real name. */
export default function PatientName({ name }: { name: string }) {
  const { t } = useTranslation()
  if (name === UNKNOWN_NAME) return <span className="text-slate-500 italic">{t('patients.tagNoName')}</span>
  return <>{name}</>
}
