import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import TemplatesEditor from '../components/TemplatesEditor'
import ScriptsEditor from '../components/ScriptsEditor'
import { Badge, Button, Card, ErrorText, Field, Input, Notice, Select } from '../components/ui'
import { api, type User } from '../lib/api'
import { useAuth } from '../lib/auth-context'
import type { Specialty } from '../lib/diagnoses'
import {
  addAbsence,
  createResource,
  deleteAbsence,
  doctorName,
  getBranches,
  getDoctorSchedule,
  getDoctors,
  getResources,
  searchServices,
  serviceName,
  setWeekly,
  syncCatalog,
  updateDoctor,
  updateResource,
  updateService,
  type Doctor,
  type Resource,
  type ServiceItem,
} from '../lib/scheduling'

const SPECIALTIES: Specialty[] = [
  'dermatologist',
  'trichologist',
  'cosmetologist',
  'oncodermatologist',
  'podologist',
]
type Row = { branch_id: string; weekday: number; start_time: string; end_time: string }

function WeeklyEditor({
  doctorId,
  initial,
  onSaved,
}: {
  doctorId: string
  initial: Row[]
  onSaved: () => void
}) {
  const { t, i18n } = useTranslation()
  const weekdays = t('weekdays', { returnObjects: true }) as string[]
  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: getBranches,
    staleTime: 300_000,
  })
  const [rows, setRows] = useState<Row[]>(initial)
  const saveRows = useMutation({ mutationFn: () => setWeekly(doctorId, rows), onSuccess: onSaved })
  const defaultBranch = branches.find((b) => b.is_main)?.id ?? branches[0]?.id ?? ''
  return (
    <div>
      <h3 className="mb-2 font-medium">{t('settings.weekly')}</h3>
      <div className="space-y-2">
        {rows.map((r, i) => (
          <div
            key={i}
            className="grid grid-cols-[4.5rem_6.5rem_6.5rem_minmax(8rem,1fr)_2rem] items-center gap-1.5"
          >
            <Select
              value={r.weekday}
              onChange={(e) =>
                setRows(rows.map((x, j) => (j === i ? { ...x, weekday: Number(e.target.value) } : x)))
              }
              className="px-2"
            >
              {weekdays.map((w, idx) => (
                <option key={idx} value={idx}>
                  {w}
                </option>
              ))}
            </Select>
            <Input
              type="time"
              step={900}
              value={r.start_time}
              onChange={(e) =>
                setRows(rows.map((x, j) => (j === i ? { ...x, start_time: e.target.value } : x)))
              }
              className="px-2"
            />
            <Input
              type="time"
              step={900}
              value={r.end_time}
              onChange={(e) =>
                setRows(rows.map((x, j) => (j === i ? { ...x, end_time: e.target.value } : x)))
              }
              className="px-2"
            />
            <Select
              value={r.branch_id}
              onChange={(e) =>
                setRows(rows.map((x, j) => (j === i ? { ...x, branch_id: e.target.value } : x)))
              }
              className="px-2"
            >
              {branches.map((b) => (
                <option key={b.id} value={b.id}>
                  {i18n.language === 'ru' ? b.name_ru : b.name_uz}
                </option>
              ))}
            </Select>
            <Button
              variant="ghost"
              onClick={() => setRows(rows.filter((_, j) => j !== i))}
              aria-label={t('app.remove')}
            >
              ✕
            </Button>
          </div>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button
          variant="secondary"
          onClick={() => {
            const used = new Set(rows.map((r) => r.weekday))
            const weekday = [0, 1, 2, 3, 4, 5].find((d) => !used.has(d)) ?? 0
            setRows([...rows, { branch_id: defaultBranch, weekday, start_time: '08:00', end_time: '18:00' }])
          }}
        >
          + {t('settings.addRow')}
        </Button>
        <Button disabled={saveRows.isPending} onClick={() => saveRows.mutate()}>
          {t('settings.save')}
        </Button>
      </div>
      {saveRows.isSuccess && <Notice>{t('settings.saved')}</Notice>}
      <ErrorText error={saveRows.error} />
    </div>
  )
}

function DoctorEditor({ doctor, isAdmin }: { doctor: Doctor; isAdmin: boolean }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const { data: users = [] } = useQuery({
    queryKey: ['users'],
    queryFn: () => api<User[]>('/users'),
    enabled: isAdmin,
  })
  const schedule = useQuery({
    queryKey: ['schedule', doctor.id],
    queryFn: () => getDoctorSchedule(doctor.id),
  })
  const [absence, setAbsence] = useState({ date_from: '', date_to: '', reason: '' })
  // the colour picker fires on every drag step; keep it local (saved by the effect below)
  const [color, setColor] = useState(doctor.color ?? '#0f766e')
  const badRange = Boolean(absence.date_from && absence.date_to && absence.date_from > absence.date_to)

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['schedule', doctor.id] })
    void queryClient.invalidateQueries({ queryKey: ['appointments'] })
  }
  const saveDoctor = useMutation({
    mutationFn: (body: Parameters<typeof updateDoctor>[1]) => updateDoctor(doctor.id, body),
    onSuccess: (saved) => {
      // the saved doctor goes straight into the list: a quick next click builds on it, not on
      // the pre-save props while the refetch is still running
      queryClient.setQueriesData<(typeof saved)[]>({ queryKey: ['doctors'] }, (list) =>
        Array.isArray(list) ? list.map((d) => (d.id === saved.id ? saved : d)) : list,
      )
      void queryClient.invalidateQueries({ queryKey: ['doctors'] })
    },
  })
  const addAbs = useMutation({
    mutationFn: () => addAbsence(doctor.id, { ...absence, reason: absence.reason || null }),
    onSuccess: () => {
      setAbsence({ date_from: '', date_to: '', reason: '' })
      refresh()
    },
  })
  const delAbs = useMutation({ mutationFn: deleteAbsence, onSuccess: refresh })
  // saved shortly after the last change: blur is unreliable with native colour pickers
  const { mutate: saveDoctorNow } = saveDoctor
  const savedColor = doctor.color ?? '#0f766e'
  useEffect(() => {
    if (color === savedColor) return
    const timer = window.setTimeout(() => saveDoctorNow({ color }), 700)
    return () => window.clearTimeout(timer)
  }, [color, savedColor, saveDoctorNow])
  return (
    <div className="space-y-5">
      <div>
        <div className="text-lg font-semibold">{doctorName(doctor, i18n.language)}</div>
        <div className="text-sm text-slate-500">
          {i18n.language === 'ru' ? doctor.title_ru : doctor.title_uz}
        </div>
      </div>

      {isAdmin && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <Field label={t('settings.specialties')}>
            <div className="space-y-1">
              {SPECIALTIES.map((s) => (
                <label key={s} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={doctor.specialties.includes(s)}
                    disabled={saveDoctor.isPending}
                    onChange={(e) =>
                      saveDoctor.mutate({
                        specialties: e.target.checked
                          ? [...doctor.specialties, s]
                          : doctor.specialties.filter((x) => x !== s),
                      })
                    }
                  />
                  {t(`diagnoses.specialties.${s}`)}
                </label>
              ))}
            </div>
          </Field>
          <Field label={t('settings.color')}>
            <Input
              type="color"
              value={color}
              onChange={(e) => setColor(e.target.value)}
              className="h-10 w-20 p-1"
            />
          </Field>
          <Field label={t('settings.linkUser')}>
            <Select
              value={doctor.user_id ?? ''}
              onChange={(e) => saveDoctor.mutate({ user_id: e.target.value || null })}
            >
              <option value="">{t('settings.noUser')}</option>
              {users
                .filter((u) => u.role === 'doctor')
                .map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.full_name} ({u.username})
                  </option>
                ))}
            </Select>
          </Field>
        </div>
      )}
      <ErrorText error={saveDoctor.error} />

      {/* fresh data only: the editor starts from it, a cached copy could overwrite newer changes */}
      {schedule.data && schedule.isFetchedAfterMount && (
        <WeeklyEditor
          key={doctor.id}
          doctorId={doctor.id}
          initial={schedule.data.rows.map((r) => ({
            ...r,
            start_time: r.start_time.slice(0, 5),
            end_time: r.end_time.slice(0, 5),
          }))}
          onSaved={refresh}
        />
      )}

      <div>
        <h3 className="mb-2 font-medium">{t('settings.absences')}</h3>
        <ul className="mb-2 space-y-1 text-sm">
          {schedule.data?.absences.map((a) => (
            <li key={a.id} className="flex items-center gap-2">
              {a.date_from} — {a.date_to} {a.reason && <span className="text-slate-500">({a.reason})</span>}
              <Button
                variant="ghost"
                className="px-2 py-0.5 text-xs"
                disabled={delAbs.isPending}
                onClick={() => delAbs.mutate(a.id)}
                aria-label={t('app.remove')}
              >
                ✕
              </Button>
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap items-end gap-2">
          <Field label={t('settings.from')}>
            <Input
              type="date"
              value={absence.date_from}
              onChange={(e) => setAbsence({ ...absence, date_from: e.target.value })}
            />
          </Field>
          <Field label={t('settings.to')}>
            <Input
              type="date"
              value={absence.date_to}
              onChange={(e) => setAbsence({ ...absence, date_to: e.target.value })}
            />
          </Field>
          <Field label={t('settings.reason')}>
            <Input
              value={absence.reason}
              onChange={(e) => setAbsence({ ...absence, reason: e.target.value })}
              maxLength={255}
            />
          </Field>
          <Button
            variant="secondary"
            disabled={!absence.date_from || !absence.date_to || badRange || addAbs.isPending}
            onClick={() => addAbs.mutate()}
          >
            {t('settings.addAbsence')}
          </Button>
        </div>
        {badRange && <p className="text-sm text-red-700">{t('errors.from_after_to')}</p>}
        <ErrorText error={addAbs.error ?? delAbs.error} />
      </div>
    </div>
  )
}

function DoctorsTab({ isAdmin }: { isAdmin: boolean }) {
  const { t, i18n } = useTranslation()
  const { data: doctors = [] } = useQuery({ queryKey: ['doctors', 'all'], queryFn: () => getDoctors(false) })
  const [selected, setSelected] = useState<string>('')
  const doctor = doctors.find((d) => d.id === selected)
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[16rem_1fr]">
      <ul className="space-y-1">
        {doctors.map((d) => (
          <li key={d.id}>
            <button
              onClick={() => setSelected(d.id)}
              className={`w-full rounded-md px-3 py-2 text-left text-sm ${selected === d.id ? 'bg-teal-50 font-medium text-teal-900' : 'hover:bg-slate-100'}`}
            >
              {d.color && (
                <span
                  className="mr-2 inline-block h-2.5 w-2.5 rounded-full"
                  style={{ background: d.color }}
                />
              )}
              {doctorName(d, i18n.language)}
              {!d.is_active && <Badge>{t('settings.inactive')}</Badge>}
            </button>
          </li>
        ))}
      </ul>
      <div>
        {doctor ? (
          <DoctorEditor key={doctor.id} doctor={doctor} isAdmin={isAdmin} />
        ) : (
          <p className="text-sm text-slate-500">{t('settings.pickDoctor')}</p>
        )}
      </div>
    </div>
  )
}

function ResourcesTab() {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: getBranches,
    staleTime: 300_000,
  })
  const { data: resources = [] } = useQuery({ queryKey: ['resources'], queryFn: () => getResources() })
  const empty = {
    branch_id: '',
    name: '',
    kind: 'device' as Resource['kind'],
    device_type: '',
    is_active: true,
  }
  const [draft, setDraft] = useState(empty)
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['resources'] })
  const create = useMutation({
    mutationFn: () =>
      createResource({
        ...draft,
        branch_id: draft.branch_id || branches[0]?.id,
        device_type: draft.kind === 'device' ? draft.device_type : null,
      }),
    onSuccess: () => {
      setDraft(empty)
      refresh()
    },
  })
  const toggle = useMutation({
    mutationFn: (r: Resource) => updateResource(r.id, { ...r, is_active: !r.is_active }),
    onSuccess: refresh,
  })
  const branchName = (id: string) => {
    const b = branches.find((x) => x.id === id)
    return b ? (i18n.language === 'ru' ? b.name_ru : b.name_uz) : ''
  }
  return (
    <div className="space-y-4">
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-slate-500 uppercase">
          <tr>
            <th className="pb-2">{t('settings.name')}</th>
            <th className="pb-2">{t('settings.kind')}</th>
            <th className="pb-2">{t('settings.deviceType')}</th>
            <th className="pb-2">{t('schedule.branch')}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {resources.map((r) => (
            <tr key={r.id} className="border-t border-slate-100">
              <td className="py-2">{r.name}</td>
              <td className="py-2">{t(`settings.${r.kind}`)}</td>
              <td className="py-2 font-mono text-xs">{r.device_type ?? '—'}</td>
              <td className="py-2">{branchName(r.branch_id)}</td>
              <td className="py-2 text-right">
                <Button
                  variant={r.is_active ? 'secondary' : 'ghost'}
                  className="px-2 py-1 text-xs"
                  onClick={() => toggle.mutate(r)}
                >
                  {r.is_active ? t('settings.active') : t('settings.inactive')}
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-5">
        <Input
          placeholder={t('settings.name')}
          value={draft.name}
          onChange={(e) => setDraft({ ...draft, name: e.target.value })}
        />
        <Select
          value={draft.kind}
          onChange={(e) => setDraft({ ...draft, kind: e.target.value as Resource['kind'] })}
        >
          <option value="device">{t('settings.device')}</option>
          <option value="room">{t('settings.room')}</option>
        </Select>
        <Input
          placeholder="laser_epilation"
          disabled={draft.kind !== 'device'}
          value={draft.device_type}
          onChange={(e) => setDraft({ ...draft, device_type: e.target.value.toLowerCase() })}
        />
        <Select
          value={draft.branch_id || branches[0]?.id || ''}
          onChange={(e) => setDraft({ ...draft, branch_id: e.target.value })}
        >
          {branches.map((b) => (
            <option key={b.id} value={b.id}>
              {i18n.language === 'ru' ? b.name_ru : b.name_uz}
            </option>
          ))}
        </Select>
        <Button disabled={!draft.name || create.isPending} onClick={() => create.mutate()}>
          {t('settings.add')}
        </Button>
      </div>
      <p className="text-xs text-slate-500">{t('settings.deviceHint')}</p>
      <ErrorText error={create.error ?? toggle.error} />
    </div>
  )
}

function ServiceRow({ s }: { s: ServiceItem }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState(s)
  const save = useMutation({
    mutationFn: () =>
      updateService(s.id, {
        duration_min: form.duration_min,
        device_type: form.device_type || null,
        min_interval_days: form.min_interval_days || null,
        course_sessions: form.course_sessions || null,
        followup_call_days: form.followup_call_days ?? null,
        is_consultation: form.is_consultation,
        requires_consultation: form.requires_consultation,
        prep_uz: form.prep_uz || null,
        prep_ru: form.prep_ru || null,
      }),
    onSuccess: () => {
      setEditing(false)
      void queryClient.invalidateQueries({ queryKey: ['services'] })
    },
  })
  const num = (v: string) => (v === '' ? null : Number(v))
  return (
    <>
      <tr className="border-t border-slate-100 align-top">
        <td className="py-2 pr-3">{serviceName(s, i18n.language)}</td>
        <td className="py-2 pr-3 tabular-nums">{s.price?.toLocaleString('ru-RU') ?? '—'}</td>
        <td className="py-2 pr-3 tabular-nums">{s.duration_min}′</td>
        <td className="py-2 pr-3 font-mono text-xs">{s.device_type ?? '—'}</td>
        <td className="py-2 pr-3 tabular-nums">{s.min_interval_days ?? '—'}</td>
        <td className="py-2 text-right">
          <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setEditing(!editing)}>
            {t('settings.edit')}
          </Button>
        </td>
      </tr>
      {editing && (
        <tr>
          <td colSpan={6} className="pb-3">
            <div className="grid grid-cols-1 gap-3 rounded-md bg-slate-50 p-3 md:grid-cols-4">
              <Field label={t('settings.durationMin')}>
                <Input
                  type="number"
                  min={5}
                  max={600}
                  value={form.duration_min}
                  onChange={(e) => setForm({ ...form, duration_min: Number(e.target.value) })}
                />
              </Field>
              <Field label={t('settings.requiredDevice')}>
                <Input
                  value={form.device_type ?? ''}
                  onChange={(e) => setForm({ ...form, device_type: e.target.value.toLowerCase() || null })}
                  placeholder="laser_epilation"
                />
              </Field>
              <Field label={t('settings.interval')}>
                <Input
                  type="number"
                  min={0}
                  value={form.min_interval_days ?? ''}
                  onChange={(e) => setForm({ ...form, min_interval_days: num(e.target.value) })}
                />
              </Field>
              <Field label={t('settings.sessions')}>
                <Input
                  type="number"
                  min={1}
                  value={form.course_sessions ?? ''}
                  onChange={(e) => setForm({ ...form, course_sessions: num(e.target.value) })}
                />
              </Field>
              <Field label={t('settings.followup')}>
                <Input
                  type="number"
                  min={0}
                  value={form.followup_call_days ?? ''}
                  onChange={(e) => setForm({ ...form, followup_call_days: num(e.target.value) })}
                />
              </Field>
              <div className="space-y-1 pt-6 text-sm">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={form.is_consultation}
                    onChange={(e) => setForm({ ...form, is_consultation: e.target.checked })}
                  />
                  {t('settings.consultation')}
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={form.requires_consultation}
                    onChange={(e) => setForm({ ...form, requires_consultation: e.target.checked })}
                  />
                  {t('settings.needsConsult')}
                </label>
              </div>
              <div className="md:col-span-2">
                <Field label={`${t('settings.prep')} (UZ)`}>
                  <Input
                    value={form.prep_uz ?? ''}
                    onChange={(e) => setForm({ ...form, prep_uz: e.target.value })}
                  />
                </Field>
                <Field label={`${t('settings.prep')} (RU)`}>
                  <Input
                    value={form.prep_ru ?? ''}
                    onChange={(e) => setForm({ ...form, prep_ru: e.target.value })}
                  />
                </Field>
              </div>
              <div className="flex items-end gap-2 md:col-span-4">
                <Button disabled={save.isPending} onClick={() => save.mutate()}>
                  {t('settings.save')}
                </Button>
                <ErrorText error={save.error} />
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

function ServicesTab() {
  const { t } = useTranslation()
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)
  const { data } = useQuery({
    queryKey: ['services', 'settings', q, offset],
    queryFn: () => searchServices({ q, offset, limit: 50 }),
    placeholderData: keepPreviousData,
  })
  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">{t('settings.siteNote')}</p>
      <Input
        type="search"
        placeholder={t('booking.searchService')}
        value={q}
        onChange={(e) => {
          setQ(e.target.value)
          setOffset(0)
        }}
      />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="text-xs text-slate-500 uppercase">
            <tr>
              <th className="pb-2">{t('settings.name')}</th>
              <th className="pb-2">{t('settings.price')}</th>
              <th className="pb-2">{t('settings.durationMin')}</th>
              <th className="pb-2">{t('settings.requiredDevice')}</th>
              <th className="pb-2">{t('settings.interval')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data?.items.map((s) => (
              <ServiceRow key={s.id} s={s} />
            ))}
          </tbody>
        </table>
      </div>
      {data && (
        <div className="flex items-center justify-between text-sm text-slate-600">
          <span>{t('patients.total', { count: data.total })}</span>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 50))}
            >
              {t('audit.prev')}
            </Button>
            <Button
              variant="secondary"
              disabled={offset + 50 >= data.total}
              onClick={() => setOffset(offset + 50)}
            >
              {t('audit.next')}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

export default function SettingsPage() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const isAdmin = user?.role === 'admin'
  const tabs = isAdmin
    ? (['doctors', 'resources', 'services', 'scripts', 'templates'] as const)
    : (['doctors', 'scripts', 'templates'] as const)
  const [tab, setTab] = useState<(typeof tabs)[number]>('doctors')
  const sync = useMutation({
    mutationFn: syncCatalog,
    onSuccess: () => void queryClient.invalidateQueries(),
  })
  return (
    <div className="max-w-6xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">{t('settings.title')}</h1>
        {isAdmin && (
          <Button variant="secondary" disabled={sync.isPending} onClick={() => sync.mutate()}>
            {t('settings.sync')}
          </Button>
        )}
      </div>
      {sync.isSuccess && <Notice>{t('settings.synced')}</Notice>}
      <ErrorText error={sync.error} />
      <div className="flex gap-1 overflow-x-auto overflow-y-hidden border-b border-slate-200 whitespace-nowrap">
        {tabs.map((k) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === k ? 'border-teal-700 font-medium text-teal-800' : 'border-transparent text-slate-600'}`}
          >
            {k === 'scripts'
              ? t('scripts.title')
              : k === 'templates'
                ? t('templates.title')
                : t(`settings.${k}`)}
          </button>
        ))}
      </div>
      <Card>
        {tab === 'doctors' && <DoctorsTab isAdmin={isAdmin} />}
        {tab === 'resources' && <ResourcesTab />}
        {tab === 'services' && <ServicesTab />}
        {tab === 'scripts' && <ScriptsEditor />}
        {tab === 'templates' && <TemplatesEditor />}
      </Card>
    </div>
  )
}
