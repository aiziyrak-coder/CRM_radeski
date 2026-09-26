import type { ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router'
import Layout from './components/Layout'
import { useAuth } from './lib/auth-context'
import { NAV_ITEMS, type NavItem } from './lib/navigation'
import AuditPage from './pages/AuditPage'
import HomePage from './pages/HomePage'
import LoginPage from './pages/LoginPage'
import ProfilePage from './pages/ProfilePage'
import SoonPage from './pages/SoonPage'
import UsersPage from './pages/UsersPage'

const PAGES: Record<string, ReactNode> = {
  '/': <HomePage />,
  '/users': <UsersPage />,
  '/audit': <AuditPage />,
  '/profile': <ProfilePage />,
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth()
  const location = useLocation()
  if (status === 'loading') return null
  if (status === 'anonymous') return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}

function Guarded({ item }: { item: NavItem }) {
  const { user } = useAuth()
  if (!user || !item.roles.includes(user.role)) return <Navigate to="/" replace />
  return PAGES[item.path] ?? <SoonPage labelKey={item.labelKey} />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          {NAV_ITEMS.map((item) => (
            <Route key={item.path} path={item.path} element={<Guarded item={item} />} />
          ))}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
