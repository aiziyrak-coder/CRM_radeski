import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  branchName,
  copySchedule,
  doctorName,
  getBranches,
  getDoctors,
  hhmmToMin,
  minToHhmm,
  setWeekly,
  type ScheduleRowIn,
} from '../lib/scheduling'
import { dayProblem, rowsToWeek, standardWeek, weekToRows, type Block, type Week } from '../lib/weekly'
import { Button, ErrorText, Input, Notice, Select } from './ui'

function CopyToDoctors({ doctorId, disabled }: { doctorId: string; disabled: boolean }) {
  const { t, i18n } = useTranslation()
  const [open, setOpen] = useState(false)
  const [picked, setPicked] = useState<string[]>([])
  const { data: doctors = [] } = useQuery({
    queryKey: ['doctors'],
    queryFn: () => getDoctors(),
    enabled: open,
  })
  const copy = useMutation({
    mutationFn: () => copySchedule(doctorId, picked),
    onSuccess: () => {
      setOpen(false)
      setPicked([])
    },
  })
  if (!open) {
    return (
      <span className="inline-flex flex-col">
        <Button variant="ghost" disabled={disabled} onClick={() => setOpen(true)}>
          {t('wsched.copy')}
        </Button>
        {disabled && <span className="px-3 text-xs text-slate-500">{t('wsched.saveFirst')}</span>}
        {copy.isSuccess && <Notice>{t('wsched.copied', { count: copy.data.doctors })}</Notice>}
      </span>
    )
  }
  const others = doctors.filter((d) => d.id !== doctorId)
  return (
    <div className="w-full rounded-md border border-slate-200 p-3">
      <p className="mb-2 text-sm text-slate-600">{t('wsched.copyHint')}</p>
      <div className="grid max-h-60 grid-cols-1 gap-1 overflow-y-auto sm:grid-cols-2">
        {others.map((d) => (
          <label key={d.id} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={picked.includes(d.id)}
              onChange={(e) =>
                setPicked(e.target.checked ? [...picked, d.id] : picked.filter((x) => x !== d.id))
              }
            />
            {doctorName(d, i18n.language)}
          </label>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button
          disabled={picked.length === 0 || copy.isPending}
          onClick={() => window.confirm(t('wsched.copyConfirm', { count: picked.length })) && copy.mutate()}
        >
          {t('wsched.copyDo', { count: picked.length })}
        </Button>
        <Button variant="ghost" onClick={() => setOpen(false)}>
          {t('patients.cancel')}
        </Button>
      </div>
      <ErrorText error={copy.error} />
    </div>
  )
}

/** Weekly hours of a doctor (TZ 4.3): per day a branch, from–to and lunch breaks. */
export default function WeeklyScheduleEditor({
  doctorId,
  initial,
  canEdit,
  onSaved,
}: {
  doctorId: string
  initial: ScheduleRowIn[]
  canEdit: boolean
  onSaved: () => void
}) {
  const { t, i18n } = useTranslation()
  const weekdays = t('weekdays', { returnObjects: true }) as string[]
  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: getBranches,
    staleTime: 300_000,
  })
  const active = branches.filter((b) => b.is_active)
  const [week, setWeek] = useState<Week>(() => rowsToWeek(initial))
  const [dirty, setDirty] = useState(false)
  const save = useMutation({
    mutationFn: () => setWeekly(doctorId, weekToRows(week)),
    onSuccess: () => {
      setDirty(false)
      onSaved()
    },
  })
  const usedBranch = week.flat()[0]?.branch_id
  const defaultBranch = usedBranch ?? active.find((b) => b.is_main)?.id ?? active[0]?.id ?? ''
  const problems = week.map(dayProblem)
  const invalid = problems.some(Boolean)

  const edit = (weekday: number, fn: (blocks: Block[]) => Block[]) => {
    setWeek((w) =>
      w.map((blocks, i) =>
        i === weekday ? fn(blocks.map((b) => ({ ...b, breaks: [...b.breaks] }))) : blocks,
      ),
    )
    setDirty(true)
    save.reset()
  }
  const setBlock = (weekday: number, idx: number, patch: Partial<Block>) =>
    edit(weekday, (blocks) => blocks.map((b, i) => (i === idx ? { ...b, ...patch } : b)))
  const addBreak = (weekday: number, idx: number) =>
    edit(weekday, (blocks) =>
      blocks.map((b, i) => {
        if (i !== idx) return b
        // default: an hour in the middle of the day, e.g. 13:00–14:00 for 08:00–18:00
        const mid = Math.floor((hhmmToMin(b.start) + hhmmToMin(b.end)) / 2 / 60) * 60
        return { ...b, breaks: [...b.breaks, { start: minToHhmm(mid), end: minToHhmm(mid + 60) }] }
      }),
    )
  const standard = () => {
    setWeek(standardWeek(defaultBranch))
    setDirty(true)
    save.reset()
  }

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium">{t('settings.weekly')}</h3>
        {canEdit && (
          <Button variant="secondary" onClick={standard} disabled={!defaultBranch}>
            {t('wsched.standard')}
          </Button>
        )}
      </div>
      <ul className="divide-y divide-slate-100 rounded-md border border-slate-200">
        {week.map((blocks, weekday) => (
          <li key={weekday} className="p-2 sm:p-3">
            <div className="flex flex-wrap items-start gap-2">
              <label className="flex w-20 shrink-0 items-center gap-2 pt-2 text-sm font-medium">
                <input
                  type="checkbox"
                  disabled={!canEdit}
                  checked={blocks.length > 0}
                  onChange={(e) =>
                    edit(weekday, () =>
                      e.target.checked
                        ? [{ branch_id: defaultBranch, start: '08:00', end: '18:00', breaks: [] }]
                        : [],
                    )
                  }
                />
                {weekdays[weekday]}
              </label>
              {blocks.length === 0 ? (
                <span className="pt-2 text-sm text-slate-400">{t('wsched.dayOff')}</span>
              ) : (
                <div className="min-w-0 flex-1 space-y-2">
                  {blocks.map((b, idx) => (
                    <div key={idx} className="space-y-1">
                      <div className="flex flex-wrap items-center gap-1.5">
                        {(active.length > 1 || blocks.length > 1) && (
                          <Select
                            value={b.branch_id}
                            disabled={!canEdit}
                            onChange={(e) => setBlock(weekday, idx, { branch_id: e.target.value })}
                            className="w-40 px-2"
                            aria-label={t('schedule.branch')}
                          >
                            {branches.map((br) => (
                              <option key={br.id} value={br.id}>
                                {branchName(br, i18n.language)}
                              </option>
                            ))}
                          </Select>
                        )}
                        <Input
                          type="time"
                          step={900}
                          value={b.start}
                          disabled={!canEdit}
                          onChange={(e) => setBlock(weekday, idx, { start: e.target.value })}
                          className="w-28 px-2"
                          aria-label={t('settings.from')}
                        />
                        <span className="text-slate-400">–</span>
                        <Input
                          type="time"
                          step={900}
                          value={b.end}
                          disabled={!canEdit}
                          onChange={(e) => setBlock(weekday, idx, { end: e.target.value })}
                          className="w-28 px-2"
                          aria-label={t('settings.to')}
                        />
                        {canEdit && (
                          <Button
                            variant="ghost"
                            className="px-2 py-1 text-xs"
                            onClick={() => addBreak(weekday, idx)}
                          >
                            + {t('wsched.break')}
                          </Button>
                        )}
                        {canEdit && blocks.length > 1 && (
                          <Button
                            variant="ghost"
                            className="px-2 py-1 text-xs"
                            aria-label={t('app.remove')}
                            onClick={() => edit(weekday, (bl) => bl.filter((_, i) => i !== idx))}
                          >
                            ✕
                          </Button>
                        )}
                      </div>
                      {b.breaks.map((br, bi) => (
                        <div
                          key={bi}
                          className="flex flex-wrap items-center gap-1.5 pl-2 text-sm text-slate-600"
                        >
                          <span className="w-20">☕ {t('wsched.break')}</span>
                          <Input
                            type="time"
                            step={900}
                            value={br.start}
                            disabled={!canEdit}
                            onChange={(e) =>
                              setBlock(weekday, idx, {
                                breaks: b.breaks.map((x, j) =>
                                  j === bi ? { ...x, start: e.target.value } : x,
                                ),
                              })
                            }
                            className="w-28 px-2"
                          />
                          <span className="text-slate-400">–</span>
                          <Input
                            type="time"
                            step={900}
                            value={br.end}
                            disabled={!canEdit}
                            onChange={(e) =>
                              setBlock(weekday, idx, {
                                breaks: b.breaks.map((x, j) =>
                                  j === bi ? { ...x, end: e.target.value } : x,
                                ),
                              })
                            }
                            className="w-28 px-2"
                          />
                          {canEdit && (
                            <Button
                              variant="ghost"
                              className="px-2 py-1 text-xs"
                              aria-label={t('app.remove')}
                              onClick={() =>
                                setBlock(weekday, idx, { breaks: b.breaks.filter((_, j) => j !== bi) })
                              }
                            >
                              ✕
                            </Button>
                          )}
                        </div>
                      ))}
                    </div>
                  ))}
                  {canEdit && active.length > 1 && (
                    <Button
                      variant="ghost"
                      className="px-2 py-1 text-xs"
                      onClick={() =>
                        edit(weekday, (bl) => {
                          const last = bl[bl.length - 1]
                          const other = active.find((br) => !bl.some((x) => x.branch_id === br.id))
                          return [
                            ...bl,
                            {
                              branch_id: other?.id ?? last.branch_id,
                              start: last.end,
                              end: '18:00',
                              breaks: [],
                            },
                          ]
                        })
                      }
                    >
                      + {t('wsched.otherBranch')}
                    </Button>
                  )}
                  {problems[weekday] && <p className="text-sm text-red-700">{t(problems[weekday]!)}</p>}
                </div>
              )}
            </div>
          </li>
        ))}
      </ul>
      {canEdit && (
        <div className="mt-3 flex flex-wrap items-start gap-2">
          <Button disabled={!dirty || invalid || save.isPending} onClick={() => save.mutate()}>
            {t('settings.save')}
          </Button>
          <CopyToDoctors doctorId={doctorId} disabled={dirty} />
        </div>
      )}
      {save.isSuccess && (
        <div className="mt-2">
          <Notice>{t('settings.saved')}</Notice>
        </div>
      )}
      <ErrorText error={save.error} />
    </div>
  )
}
