import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getTemplates, updateTemplate, type MessageTemplate } from '../lib/messaging'
import { Button, ErrorText, Input } from './ui'

function Row({ tpl }: { tpl: MessageTemplate }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [form, setForm] = useState({ title: tpl.title, text: tpl.text, active: tpl.active })
  const dirty = form.title !== tpl.title || form.text !== tpl.text || form.active !== tpl.active
  const save = useMutation({
    mutationFn: () => updateTemplate(tpl.id, form),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['inbox', 'templates'] }),
  })
  return (
    <li className="space-y-2 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-slate-500">
          {tpl.code} · {tpl.language.toUpperCase()}
        </span>
        <Input
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
          className="flex-1"
        />
        <label className="flex items-center gap-1 text-sm">
          <input
            type="checkbox"
            checked={form.active}
            onChange={(e) => setForm({ ...form, active: e.target.checked })}
          />
          {t('ai.active')}
        </label>
      </div>
      <textarea
        value={form.text}
        onChange={(e) => setForm({ ...form, text: e.target.value })}
        rows={3}
        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
      />
      <div className="flex items-center gap-2">
        {dirty && (
          <Button className="px-2 py-1 text-xs" disabled={save.isPending} onClick={() => save.mutate()}>
            {t('patients.save')}
          </Button>
        )}
        <span className="text-xs text-slate-500">{t('templates.chars', { n: form.text.length })}</span>
        <ErrorText error={save.error} />
      </div>
    </li>
  )
}

export default function TemplatesEditor() {
  const { t } = useTranslation()
  const { data, error } = useQuery({ queryKey: ['inbox', 'templates'], queryFn: getTemplates })
  return (
    <div>
      <p className="mb-2 text-xs text-slate-500">{t('templates.hint')}</p>
      <ErrorText error={error} />
      <ul className="divide-y divide-slate-100">
        {data?.map((tpl) => (
          <Row key={`${tpl.id}-${tpl.text}-${tpl.active}-${tpl.title}`} tpl={tpl} />
        ))}
      </ul>
    </div>
  )
}
