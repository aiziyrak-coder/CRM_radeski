import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Badge, Button, Card, ErrorText, Field, Input, Select } from '../components/ui'
import { categoryName, getCategories } from '../lib/diagnoses'
import {
  createCampaign,
  getCampaigns,
  getScripts,
  previewSegment,
  setCampaignStatus,
  type Campaign,
  type Segment,
} from '../lib/ops'
import { KINDS, getDistricts, type PatientKind } from '../lib/patients'

function MultiChips<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: string }[]
  value: T[]
  onChange: (v: T[]) => void
  label: (v: T) => string
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const on = value.includes(o.value)
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(on ? value.filter((x) => x !== o.value) : [...value, o.value])}
            className={`rounded-full border px-2.5 py-1 text-xs ${on ? 'border-teal-600 bg-teal-50 text-teal-900' : 'border-slate-200 text-slate-700'}`}
          >
            {label(o.value)}
          </button>
        )
      })}
    </div>
  )
}

function NewCampaign({ onClose }: { onClose: () => void }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const { data: categories = [] } = useQuery({
    queryKey: ['diagnoses', 'categories'],
    queryFn: getCategories,
  })
  const { data: districts = [] } = useQuery({
    queryKey: ['districts'],
    queryFn: getDistricts,
    staleTime: Infinity,
  })
  const { data: scripts = [] } = useQuery({ queryKey: ['scripts'], queryFn: () => getScripts() })
  const [name, setName] = useState('')
  const [segment, setSegment] = useState<Segment>({ kinds: ['legacy'] })
  const [limit, setLimit] = useState(30)
  const [script, setScript] = useState('reactivation')
  const preview = useMutation({ mutationFn: () => previewSegment(segment) })
  const create = useMutation({
    mutationFn: () => createCampaign({ name, segment, script_code: script, daily_limit: limit }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['campaigns'] })
      onClose()
    },
  })
  const set = (patch: Partial<Segment>) => {
    setSegment({ ...segment, ...patch })
    preview.reset()
  }
  const num = (v: string) => (v === '' ? undefined : Number(v))

  return (
    <Card title={t('campaigns.new')}>
      <div className="space-y-4">
        <p className="text-xs text-slate-500">{t('campaigns.hint')}</p>
        <Field label={t('campaigns.name')}>
          <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={255} />
        </Field>
        <Field label={t('campaigns.kinds')}>
          <MultiChips
            options={KINDS.map((k) => ({ value: k, label: k }))}
            value={segment.kinds ?? []}
            onChange={(v) => set({ kinds: v as PatientKind[] })}
            label={(v) => t(`kinds.${v}`)}
          />
        </Field>
        <Field label={t('campaigns.categories')}>
          <MultiChips
            options={categories.filter((c) => c.patients > 0).map((c) => ({ value: c.code, label: c.code }))}
            value={segment.categories ?? []}
            onChange={(v) => set({ categories: v })}
            label={(v) => {
              const c = categories.find((x) => x.code === v)
              return c ? `${categoryName(c, i18n.language)} (${c.patients})` : v
            }}
          />
        </Field>
        <Field label={t('campaigns.districts')}>
          <MultiChips
            options={districts.map((d) => ({ value: d, label: d }))}
            value={segment.districts ?? []}
            onChange={(v) => set({ districts: v })}
            label={(v) => v}
          />
        </Field>
        <div className="grid gap-3 md:grid-cols-4">
          <Field label={t('campaigns.lastVisit')}>
            <Input
              type="number"
              min={1}
              value={segment.last_visit_before_days ?? ''}
              onChange={(e) => set({ last_visit_before_days: num(e.target.value) })}
            />
          </Field>
          <Field label={t('campaigns.gender')}>
            <Select
              value={segment.gender ?? ''}
              onChange={(e) => set({ gender: (e.target.value || undefined) as Segment['gender'] })}
            >
              <option value="">{t('campaigns.any')}</option>
              <option value="female">{t('genders.female')}</option>
              <option value="male">{t('genders.male')}</option>
            </Select>
          </Field>
          <Field label={t('campaigns.ageMin')}>
            <Input
              type="number"
              min={0}
              value={segment.age_min ?? ''}
              onChange={(e) => set({ age_min: num(e.target.value) })}
            />
          </Field>
          <Field label={t('campaigns.ageMax')}>
            <Input
              type="number"
              min={0}
              value={segment.age_max ?? ''}
              onChange={(e) => set({ age_max: num(e.target.value) })}
            />
          </Field>
          <Field label={t('campaigns.script')}>
            <Select value={script} onChange={(e) => setScript(e.target.value)}>
              {[...new Set(scripts.map((s) => s.code))].map((code) => (
                <option key={code} value={code}>
                  {scripts.find(
                    (s) => s.code === code && s.language === (i18n.language === 'ru' ? 'ru' : 'uz'),
                  )?.title ?? code}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t('campaigns.dailyLimit')}>
            <Input
              type="number"
              min={1}
              max={500}
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
            />
          </Field>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" disabled={preview.isPending} onClick={() => preview.mutate()}>
            {t('campaigns.preview')}
          </Button>
          {preview.data && (
            <span className="text-sm font-medium">
              {t('campaigns.audience', { count: preview.data.audience })}
            </span>
          )}
          <span className="flex-1" />
          <Button variant="secondary" onClick={onClose}>
            {t('patients.cancel')}
          </Button>
          <Button disabled={name.trim().length < 2 || create.isPending} onClick={() => create.mutate()}>
            {t('campaigns.create')}
          </Button>
        </div>
        <ErrorText error={preview.error ?? create.error} />
      </div>
    </Card>
  )
}

function CampaignRow({ c }: { c: Campaign }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const change = useMutation({
    mutationFn: (s: Campaign['status']) => setCampaignStatus(c.id, s),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['campaigns'] })
      void queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
  })
  const results = Object.entries(c.stats).filter(([k]) => !['total', 'open'].includes(k))
  return (
    <tr className="border-t border-slate-100 align-top">
      <td className="py-2 pr-3 font-medium">{c.name}</td>
      <td className="py-2 pr-3">
        <Badge tone={c.status === 'active' ? 'good' : 'neutral'}>{t(`campaigns.statuses.${c.status}`)}</Badge>
      </td>
      <td className="py-2 pr-3 tabular-nums">{c.audience}</td>
      <td className="py-2 pr-3 tabular-nums">{c.daily_limit}</td>
      <td className="py-2 pr-3 text-xs">
        {c.stats.total} / {c.stats.open} {t('tasks.title').toLowerCase()}
        {results.length > 0 && (
          <div className="text-slate-600">
            {results.map(([k, n]) => `${t(`outcomes.${k}`, { defaultValue: k })}: ${n}`).join(' · ')}
          </div>
        )}
      </td>
      <td className="py-2 text-right whitespace-nowrap">
        {c.status !== 'active' && c.status !== 'finished' && (
          <Button
            className="px-2 py-1 text-xs"
            disabled={change.isPending}
            onClick={() => change.mutate('active')}
          >
            {t('campaigns.activate')}
          </Button>
        )}
        {c.status === 'active' && (
          <Button
            variant="secondary"
            className="px-2 py-1 text-xs"
            disabled={change.isPending}
            onClick={() => change.mutate('paused')}
          >
            {t('campaigns.pause')}
          </Button>
        )}
        {c.status !== 'finished' && (
          <Button
            variant="ghost"
            className="px-2 py-1 text-xs"
            disabled={change.isPending}
            onClick={() => change.mutate('finished')}
          >
            {t('campaigns.finish')}
          </Button>
        )}
      </td>
    </tr>
  )
}

export default function CampaignsPage() {
  const { t } = useTranslation()
  const [adding, setAdding] = useState(false)
  const { data: campaigns, error } = useQuery({ queryKey: ['campaigns'], queryFn: getCampaigns })
  return (
    <div className="max-w-6xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">{t('campaigns.title')}</h1>
        {!adding && <Button onClick={() => setAdding(true)}>{t('campaigns.new')}</Button>}
      </div>
      {adding && <NewCampaign onClose={() => setAdding(false)} />}
      <Card>
        <ErrorText error={error} />
        {campaigns && campaigns.length === 0 && (
          <p className="text-sm text-slate-500">{t('campaigns.empty')}</p>
        )}
        {campaigns && campaigns.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead className="text-xs text-slate-500 uppercase">
                <tr>
                  <th className="pb-2">{t('campaigns.name')}</th>
                  <th className="pb-2" />
                  <th className="pb-2">{t('campaigns.segment')}</th>
                  <th className="pb-2">{t('campaigns.dailyLimit')}</th>
                  <th className="pb-2">{t('campaigns.stats')}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {campaigns.map((c) => (
                  <CampaignRow key={c.id} c={c} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
