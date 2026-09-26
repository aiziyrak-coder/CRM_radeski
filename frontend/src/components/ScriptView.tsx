import { useQuery } from '@tanstack/react-query'
import { Fragment, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { Language } from '../lib/api'
import { fillScript, getScripts } from '../lib/ops'
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

export default function ScriptButton({
  code,
  language,
  values,
}: {
  code: string | null
  language: Language | null
  values: Record<string, string | null | undefined>
}) {
  const { t, i18n } = useTranslation()
  const [open, setOpen] = useState(false)
  const [lang, setLang] = useState<Language>(language ?? (i18n.language === 'ru' ? 'ru' : 'uz'))
  const { data: scripts = [] } = useQuery({
    queryKey: ['scripts'],
    queryFn: () => getScripts(),
    staleTime: 600_000,
    enabled: open,
  })
  if (!code) return null
  const script = scripts.find((s) => s.code === code && s.language === lang)
  return (
    <>
      <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => setOpen(true)}>
        {t('tasks.script')}
      </Button>
      {open && (
        <Modal title={script?.title ?? t('tasks.script')} onClose={() => setOpen(false)} wide>
          <div className="mb-3 flex gap-1">
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
          {script ? (
            <ScriptBody body={fillScript(script.body, values)} />
          ) : (
            <p className="text-sm text-slate-500">{t('app.loading')}</p>
          )}
        </Modal>
      )}
    </>
  )
}
