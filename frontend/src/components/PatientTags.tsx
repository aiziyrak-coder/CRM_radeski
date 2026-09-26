import { useTranslation } from 'react-i18next'
import { TAG_LABELS } from '../lib/patients'
import { Badge } from './ui'

export default function PatientTags({ tags }: { tags: string[] }) {
  const { t } = useTranslation()
  // "ismsiz" is already conveyed by the placeholder name
  const shown = tags.filter((tag) => tag !== 'ismsiz')
  if (shown.length === 0) return null
  return (
    <span className="inline-flex flex-wrap gap-1">
      {shown.map((tag) => (
        <Badge key={tag} tone={tag === 'tekshirish-kerak' ? 'info' : 'neutral'}>
          {TAG_LABELS[tag] ? t(TAG_LABELS[tag]) : tag}
        </Badge>
      ))}
    </span>
  )
}
