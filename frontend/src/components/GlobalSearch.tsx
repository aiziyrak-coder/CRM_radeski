import { useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { formatPhone, searchPatients, UNKNOWN_NAME } from '../lib/patients'
import { Avatar, Badge } from './ui'
import { cx } from '../lib/cx'

/** Header search: find a patient by name (Cyrillic or Latin) or any part of the phone, from any
 * page. "/" focuses it; arrows + Enter open the card. */
export default function GlobalSearch() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [debounced, setDebounced] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(q.trim()), 250)
    return () => window.clearTimeout(id)
  }, [q])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)
      if (e.key === '/' && !typing) {
        e.preventDefault()
        input.current?.focus()
      }
    }
    const onClick = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onClick)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onClick)
    }
  }, [])

  const { data, isFetching } = useQuery({
    queryKey: ['patients', 'global-search', debounced],
    queryFn: () => searchPatients({ q: debounced, offset: 0, limit: 8 }),
    enabled: debounced.length >= 2,
    staleTime: 30_000,
  })
  const items = debounced.length >= 2 ? (data?.items ?? []) : []
  const go = (id: string) => {
    setOpen(false)
    setQ('')
    navigate(`/patients/${id}`)
  }

  return (
    <div className="relative w-full max-w-md" ref={box}>
      <Search
        className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-slate-400"
        aria-hidden
      />
      <input
        ref={input}
        type="search"
        value={q}
        onChange={(e) => {
          setQ(e.target.value)
          setOpen(true)
          setActive(0)
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') setActive((a) => Math.min(a + 1, items.length - 1))
          else if (e.key === 'ArrowUp') setActive((a) => Math.max(a - 1, 0))
          else if (e.key === 'Enter' && items[active]) go(items[active].id)
          else if (e.key === 'Escape') setOpen(false)
        }}
        placeholder={t('search.placeholder')}
        aria-label={t('search.placeholder')}
        className="w-full rounded-lg border border-slate-200 bg-slate-50 py-2 pr-10 pl-9 text-sm outline-none placeholder:text-slate-400 focus:border-teal-600 focus:bg-white focus:ring-2 focus:ring-teal-600/20"
      />
      <kbd className="absolute top-1/2 right-2.5 hidden -translate-y-1/2 rounded border border-slate-200 bg-white px-1.5 text-[11px] text-slate-400 sm:block">
        /
      </kbd>
      {open && debounced.length >= 2 && (
        <div className="absolute top-full right-0 left-0 z-40 mt-1 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg">
          {items.length === 0 ? (
            <p className="px-4 py-3 text-sm text-slate-500">
              {isFetching ? t('app.loading') : t('search.none')}
            </p>
          ) : (
            <ul>
              {items.map((p, i) => {
                const name = p.full_name === UNKNOWN_NAME ? t('patients.tagNoName') : p.full_name
                return (
                  <li key={p.id}>
                    <button
                      className={cx(
                        'flex w-full items-center gap-3 px-4 py-2.5 text-left',
                        i === active ? 'bg-teal-50' : 'hover:bg-slate-50',
                      )}
                      onMouseEnter={() => setActive(i)}
                      onClick={() => go(p.id)}
                    >
                      <Avatar name={name} size="sm" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-slate-900">{name}</span>
                        <span className="block text-xs text-slate-500 tabular-nums">
                          {formatPhone(
                            (p.phones.find((ph) => ph.is_primary) ?? p.phones[0])?.number ?? null,
                          ) || '—'}
                        </span>
                      </span>
                      <Badge>{t(`kinds.${p.kind}`)}</Badge>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
          <p className="border-t border-slate-100 bg-slate-50 px-4 py-2 text-[11px] text-slate-500">
            {t('search.hint')}
          </p>
        </div>
      )}
    </div>
  )
}
