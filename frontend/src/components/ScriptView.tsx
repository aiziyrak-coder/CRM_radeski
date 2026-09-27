import { useQuery } from '@tanstack/react-query'
import { Fragment, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { Language } from '../lib/api'
import { OBJECTIONS, fillScript, getScripts } from '../lib/ops'
import { Button, Modal } from './ui'

/** Minimal formatting used in the scripts: **bold** and _italic_ within lines. */
function renderInline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|_[^_]+_)/g).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={i}>{part.slice(2, -2)}</strong>
    if (part.startsWith('_') && part.endsWith('_') && part.length > 2)
      return (
        <em key={i} className="text-slate-600">
          {part.slice(1, -1)}
        </em>
      )
    return <Fragment key={i}>{part}</Fragment>
  })
}

export function ScriptBody({ body }: { body: string }) {
  return (
    <div className="space-y-2 text-sm leading-relaxed">
      {body.split(/\n{2,}/).map((para, i) => (
        <p key={i}>
          {para.split('\n').map((line, j) => (
            <Fragment key={j}>
              {j > 0 && <br />}
              {renderInline(line)}
            </Fragment>
          ))}
        </p>
      ))}
    </div>
  )
}

/** placeholder values, or a function of the script's language (doctor / service names differ) */
export type ScriptValues =
  Record<string, string | null | undefined> | ((lang: Language) => Record<string, string | null | undefined>)

const resolve = (values: ScriptValues, lang: Language) =>
  typeof values === 'function' ? values(lang) : values

function useScripts(enabled = true) {
  return useQuery({
    queryKey: ['scripts'],
    queryFn: () => getScripts(),
    staleTime: 600_000,
    enabled,
  })
}

function LangToggle({ lang, onChange }: { lang: Language; onChange: (l: Language) => void }) {
  return (
    <div className="flex gap-1" role="group">
      {(['uz', 'ru'] as const).map((l) => (
        <Button
          key={l}
          variant={l === lang ? 'primary' : 'secondary'}
          className="px-2 py-0.5 text-xs"
          aria-pressed={l === lang}
          onClick={() => onChange(l)}
        >
          {l.toUpperCase()}
        </Button>
      ))}
    </div>
  )
}

/**
 * TZ 4.6 "E'tirozlar": the objection scripts are kept apart from the call script; one button each
 * opens the answer right under it (a second click closes it).
 */
export function Objections({ lang, values }: { lang: Language; values: ScriptValues }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState<string | null>(null)
  const { data: scripts = [] } = useScripts()
  const script = open ? scripts.find((s) => s.code === open && s.language === lang) : null
  return (
    <div className="rounded-md border border-amber-200 bg-amber-50/60 p-3">
      <div className="mb-2 text-xs font-semibold tracking-wide text-amber-900 uppercase">
        {t('taskQueue.objections')}
      </div>
      <div className="flex flex-wrap gap-1">
        {OBJECTIONS.map((code) => (
          <Button
            key={code}
            variant={open === code ? 'primary' : 'secondary'}
            className="px-2 py-1 text-xs"
            aria-expanded={open === code}
            onClick={() => setOpen(open === code ? null : code)}
          >
            {t(`taskQueue.objection.${code}`)}
          </Button>
        ))}
      </div>
      {open && (
        <div className="mt-3 rounded-md bg-white p-3">
          {script ? (
            <ScriptBody body={fillScript(script.body, resolve(values, lang))} />
          ) : (
            <p className="text-sm text-slate-500">{t('taskQueue.noScript')}</p>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * The task's script inline (opened together with the result form), in the patient's language with
 * a manual switch, placeholders filled; the objection answers below it.
 */
export function ScriptPanel({
  code,
  language,
  values,
}: {
  code: string | null
  language: Language | null
  values: ScriptValues
}) {
  const { t, i18n } = useTranslation()
  const [lang, setLang] = useState<Language>(language ?? (i18n.language === 'ru' ? 'ru' : 'uz'))
  const [collapsed, setCollapsed] = useState(false)
  const { data: scripts, isLoading } = useScripts()
  const script = scripts?.find((s) => s.code === code && s.language === lang)
  return (
    <div className="space-y-3 rounded-md border border-teal-100 bg-teal-50/40 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button
          className="text-left text-sm font-semibold text-teal-900 hover:underline"
          aria-expanded={!collapsed}
          onClick={() => setCollapsed(!collapsed)}
        >
          {collapsed ? '▸' : '▾'} {script?.title ?? t('tasks.script')}
        </button>
        <LangToggle lang={lang} onChange={setLang} />
      </div>
      {!collapsed && (
        <div className="max-h-80 overflow-y-auto rounded-md bg-white p-3">
          {script ? (
            <ScriptBody body={fillScript(script.body, resolve(values, lang))} />
          ) : (
            <p className="text-sm text-slate-500">{isLoading ? t('app.loading') : t('taskQueue.noScript')}</p>
          )}
        </div>
      )}
      <Objections lang={lang} values={values} />
    </div>
  )
}

export default function ScriptButton({
  code,
  language,
  values,
}: {
  code: string | null
  language: Language | null
  values: ScriptValues
}) {
  const { t, i18n } = useTranslation()
  const [open, setOpen] = useState(false)
  const [lang, setLang] = useState<Language>(language ?? (i18n.language === 'ru' ? 'ru' : 'uz'))
  const { data: scripts = [] } = useScripts(open)
  if (!code) return null
  const script = scripts.find((s) => s.code === code && s.language === lang)
  return (
    <>
      <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => setOpen(true)}>
        {t('tasks.script')}
      </Button>
      {open && (
        <Modal title={script?.title ?? t('tasks.script')} onClose={() => setOpen(false)} wide>
          <div className="mb-3">
            <LangToggle lang={lang} onChange={setLang} />
          </div>
          {script ? (
            <ScriptBody body={fillScript(script.body, resolve(values, lang))} />
          ) : (
            <p className="text-sm text-slate-500">{t('app.loading')}</p>
          )}
          <div className="mt-4">
            <Objections lang={lang} values={values} />
          </div>
        </Modal>
      )}
    </>
  )
}
