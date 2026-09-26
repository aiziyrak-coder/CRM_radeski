import { Component, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation } from 'react-router'

function Fallback({ onRetry }: { onRetry: () => void }) {
  const { t } = useTranslation()
  return (
    <div
      role="alert"
      className="max-w-xl rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-900"
    >
      <p>{t('errors.page')}</p>
      <button className="mt-2 font-medium underline" onClick={onRetry}>
        {t('errors.reload')}
      </button>
    </div>
  )
}

type Props = { children: ReactNode; resetKey: string }
type State = { failed: boolean; key: string }

/** One broken page (a render error) must not blank the whole app: the menu and the softphone
 * stay usable, and moving to another page clears the error. */
class Boundary extends Component<Props, State> {
  state: State = { failed: false, key: this.props.resetKey }

  static getDerivedStateFromError(): Partial<State> {
    return { failed: true }
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    return props.resetKey !== state.key ? { failed: false, key: props.resetKey } : null
  }

  componentDidCatch(error: unknown) {
    console.error(error)
  }

  render() {
    if (this.state.failed) return <Fallback onRetry={() => window.location.reload()} />
    return this.props.children
  }
}

export default function PageErrorBoundary({ children }: { children: ReactNode }) {
  const { pathname } = useLocation()
  return <Boundary resetKey={pathname}>{children}</Boundary>
}
