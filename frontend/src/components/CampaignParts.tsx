import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { setCampaignStatus, type Campaign, type CampaignStatus, type Segment } from '../lib/campaigns'
import { categoryName, type Category } from '../lib/diagnoses'
import { Button, ErrorText } from './ui'

export function MultiChips<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: T[]
  value: T[]
  onChange: (v: T[]) => void
  label: (v: T) => string
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const on = value.includes(o)
        return (
          <button
            key={o}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(on ? value.filter((x) => x !== o) : [...value, o])}
            className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${on ? 'border-teal-600 bg-teal-50 text-teal-900' : 'border-slate-200 text-slate-700 hover:border-slate-300'}`}
          >
            {label(o)}
          </button>
        )
      })}
    </div>
  )
}

/** Human-readable chips for a stored segment ("Eski baza", "Akne", "180+ kun", ...). */
export function SegmentChips({ segment, categories }: { segment: Segment; categories: Category[] }) {
  const { t, i18n } = useTranslation()
  const parts: string[] = [
    ...(segment.kinds ?? []).map((k) => t(`kinds.${k}`)),
    ...(segment.categories ?? []).map((code) => {
      const c = categories.find((x) => x.code === code)
      return c ? categoryName(c, i18n.language) : code
    }),
    ...(segment.districts ?? []),
    ...(segment.sources ?? []).map((s) => t(`sources.${s}`)),
    ...(segment.tags ?? []).map((tag) => `#${tag}`),
  ]
  if (segment.gender) parts.push(t(`genders.${segment.gender}`))
  if (segment.last_visit_before_days)
    parts.push(t('campaigns.seg.lastVisit', { n: segment.last_visit_before_days }))
  if (segment.age_min != null || segment.age_max != null)
    parts.push(t('campaigns.seg.age', { from: segment.age_min ?? 0, to: segment.age_max ?? '…' }))
  if (parts.length === 0) return <span className="text-xs text-slate-500">{t('campaigns.seg.everyone')}</span>
  return (
    <div className="flex flex-wrap gap-1">
      {parts.map((p, i) => (
        <span key={i} className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-700">
          {p}
        </span>
      ))}
    </div>
  )
}

export function ProgressBar({ percent, className = '' }: { percent: number; className?: string }) {
  return (
    <div
      className={`h-2 overflow-hidden rounded-full bg-slate-100 ${className}`}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(percent)}
    >
      <div className="h-full rounded-full bg-teal-600" style={{ width: `${Math.min(100, percent)}%` }} />
    </div>
  )
}

export function StatusActions({ c, compact }: { c: Campaign; compact?: boolean }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const change = useMutation({
    mutationFn: (s: CampaignStatus) => setCampaignStatus(c.id, s),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['campaigns'] })
      void queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
  })
  const size = compact ? 'px-2 py-1 text-xs' : ''
  return (
    <div className="flex flex-wrap items-center justify-end gap-1.5">
      {(c.status === 'draft' || c.status === 'paused') && (
        <Button className={size} disabled={change.isPending} onClick={() => change.mutate('active')}>
          {c.status === 'paused' ? t('campaigns.resume') : t('campaigns.activate')}
        </Button>
      )}
      {c.status === 'active' && (
        <Button
          variant="secondary"
          className={size}
          disabled={change.isPending}
          onClick={() => change.mutate('paused')}
        >
          {t('campaigns.pause')}
        </Button>
      )}
      {c.status !== 'finished' && (
        <Button
          variant="ghost"
          className={size}
          disabled={change.isPending}
          onClick={() => {
            // finishing is final: the campaign's open calls are cancelled
            if (window.confirm(t('campaigns.finishConfirm'))) change.mutate('finished')
          }}
        >
          {t('campaigns.finish')}
        </Button>
      )}
      <ErrorText error={change.error} />
    </div>
  )
}
