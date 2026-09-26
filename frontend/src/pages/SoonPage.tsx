import { useTranslation } from 'react-i18next'
import { Card } from '../components/ui'

export default function SoonPage({ labelKey }: { labelKey: string }) {
  const { t } = useTranslation()
  return (
    <div className="max-w-2xl">
      <h1 className="mb-4 text-2xl font-semibold">{t(labelKey)}</h1>
      <Card>
        <p className="font-medium">{t('soon.title')}</p>
        <p className="mt-1 text-sm text-slate-600">{t('soon.text', { name: t(labelKey) })}</p>
      </Card>
    </div>
  )
}
