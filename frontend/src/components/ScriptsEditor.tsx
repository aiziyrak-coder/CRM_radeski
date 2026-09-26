import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Language } from '../lib/api'
import { getScripts, saveScript, type Script } from '../lib/ops'
import { ScriptBody } from './ScriptView'
import { Button, ErrorText, Field, Input, Notice } from './ui'

function Editor({ script }: { script: Script }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [title, setTitle] = useState(script.title)
  const [body, setBody] = useState(script.body)
  const save = useMutation({
    mutationFn: () => saveScript(script.code, script.language, { title, body }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['scripts'] }),
  })
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="space-y-3">
        <Field label={t('settings.name')}>
          <Input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={255} />
        </Field>
        <textarea
          className="h-96 w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm"
          value={body}
          onChange={(e) => setBody(e.target.value)}
        />
        <p className="text-xs text-slate-500">{t('scripts.hint')} · **qalin** · _kursiv_</p>
        <div className="flex items-center gap-2">
          <Button disabled={save.isPending || !title.trim() || !body.trim()} onClick={() => save.mutate()}>
            {t('scripts.save')}
          </Button>
          {save.isSuccess && <Notice>{t('scripts.saved')}</Notice>}
          <ErrorText error={save.error} />
        </div>
      </div>
      <div className="rounded-md border border-slate-200 p-4">
        <ScriptBody body={body} />
      </div>
    </div>
  )
}

export default function ScriptsEditor() {
  const { i18n } = useTranslation()
  const [lang, setLang] = useState<Language>(i18n.language === 'ru' ? 'ru' : 'uz')
  const { data: scripts = [] } = useQuery({ queryKey: ['scripts'], queryFn: () => getScripts() })
  const list = scripts.filter((s) => s.language === lang)
  const [code, setCode] = useState('')
  const current = list.find((s) => s.code === code) ?? list[0]
  return (
    <div className="grid gap-6 lg:grid-cols-[16rem_1fr]">
      <div>
        <div className="mb-2 flex gap-1">
          {(['uz', 'ru'] as const).map((l) => (
            <Button
              key={l}
              variant={l === lang ? 'primary' : 'secondary'}
              className="px-2 py-1 text-xs"
              onClick={() => setLang(l)}
            >
              {l.toUpperCase()}
            </Button>
          ))}
        </div>
        <ul className="space-y-1">
          {list.map((s) => (
            <li key={s.id}>
              <button
                onClick={() => setCode(s.code)}
                className={`w-full rounded-md px-3 py-2 text-left text-sm ${current?.id === s.id ? 'bg-teal-50 font-medium text-teal-900' : 'hover:bg-slate-100'}`}
              >
                {s.title}
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div>{current && <Editor key={current.id} script={current} />}</div>
    </div>
  )
}
