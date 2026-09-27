import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { CHECK_TAG, TAG_LABELS, getTags, updatePatient, type Patient } from '../lib/patients'
import { Badge, ErrorText } from './ui'

export default function PatientTags({ tags }: { tags: string[] }) {
  const { t } = useTranslation()
  // "ismsiz" is already conveyed by the placeholder name
  const shown = tags.filter((tag) => tag !== 'ismsiz')
  if (shown.length === 0) return null
  return (
    <span className="inline-flex flex-wrap gap-1">
      {shown.map((tag) => (
        <Badge key={tag} tone={tag === CHECK_TAG ? 'info' : 'neutral'}>
          {TAG_LABELS[tag] ? t(TAG_LABELS[tag]) : tag}
        </Badge>
      ))}
    </span>
  )
}

const MAX_TAGS = 20 // backend PatientBase.tags

/** Tag chips with remove buttons and an add field (suggests tags already in use). */
export function TagEditor({ patient, onSaved }: { patient: Patient; onSaved: (p: Patient) => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [adding, setAdding] = useState(false)
  const [text, setText] = useState('')
  const { data: known = [] } = useQuery({
    queryKey: ['patients', 'tags'],
    queryFn: getTags,
    staleTime: 60_000,
    enabled: adding,
  })
  const save = useMutation({
    mutationFn: (tags: string[]) => updatePatient(patient.id, { tags }),
    onSuccess: (p) => {
      onSaved(p)
      setText('')
      void queryClient.invalidateQueries({ queryKey: ['patients', 'tags'] })
    },
  })
  const add = (e: FormEvent) => {
    e.preventDefault()
    const tag = text.trim().toLowerCase().replace(/\s+/g, '-').slice(0, 50)
    if (!tag || patient.tags.includes(tag)) return setText('')
    save.mutate([...patient.tags, tag])
  }
  const label = (tag: string) => (TAG_LABELS[tag] ? t(TAG_LABELS[tag]) : tag)
  return (
    <div className="flex flex-wrap items-center gap-1">
      {patient.tags.map((tag) => (
        <span
          key={tag}
          className={`inline-flex items-center gap-1 rounded-full py-0.5 pr-1 pl-2.5 text-xs font-medium ${
            tag === CHECK_TAG ? 'bg-amber-50 text-amber-800' : 'bg-slate-100 text-slate-700'
          }`}
        >
          {label(tag)}
          <button
            className="rounded-full px-1 text-slate-500 hover:bg-white hover:text-red-700"
            aria-label={t('patientCard.removeTag', { tag: label(tag) })}
            disabled={save.isPending}
            onClick={() => save.mutate(patient.tags.filter((x) => x !== tag))}
          >
            ×
          </button>
        </span>
      ))}
      {adding ? (
        <form onSubmit={add} className="inline-flex items-center gap-1">
          <input
            list="patient-tags"
            className="w-36 rounded-full border border-slate-300 px-2.5 py-0.5 text-xs outline-none focus:border-teal-600"
            placeholder={t('patientCard.tagPlaceholder')}
            value={text}
            maxLength={50}
            autoFocus
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === 'Escape' && setAdding(false)}
          />
          <datalist id="patient-tags">
            {known
              .filter((k) => !patient.tags.includes(k.tag))
              .map((k) => (
                <option key={k.tag} value={k.tag}>
                  {label(k.tag)}
                </option>
              ))}
          </datalist>
          <button
            type="submit"
            className="rounded-full bg-teal-700 px-2.5 py-0.5 text-xs font-medium text-white disabled:opacity-50"
            disabled={!text.trim() || save.isPending}
          >
            {t('patientCard.addTag')}
          </button>
          <button type="button" className="px-1 text-xs text-slate-500" onClick={() => setAdding(false)}>
            {t('patients.cancel')}
          </button>
        </form>
      ) : (
        patient.tags.length < MAX_TAGS && (
          <button
            className="rounded-full border border-dashed border-slate-300 px-2.5 py-0.5 text-xs text-slate-600 hover:border-teal-600 hover:text-teal-800"
            onClick={() => setAdding(true)}
          >
            + {t('patientCard.tag')}
          </button>
        )
      )}
      <ErrorText error={save.error} />
    </div>
  )
}
