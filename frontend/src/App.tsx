import type { ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router'
import Layout from './components/Layout'
import { useAuth } from './lib/auth-context'
import { NAV_ITEMS, type NavItem } from './lib/navigation'
import AuditPage from './pages/AuditPage'
import CampaignsPage from './pages/CampaignsPage'
import LeadsPage from './pages/LeadsPage'
import ReportsPage from './pages/ReportsPage'
import TasksPage from './pages/TasksPage'
import DiagnosesPage from './pages/DiagnosesPage'
import HomePage from './pages/HomePage'
import MyDayPage from './pages/MyDayPage'
import PatientCardPage from './pages/PatientCardPage'
import PatientsPage from './pages/PatientsPage'
import LoginPage from './pages/LoginPage'
import ProfilePage from './pages/ProfilePage'
import SchedulePage from './pages/SchedulePage'
import SettingsPage from './pages/SettingsPage'
import SoonPage from './pages/SoonPage'
import UsersPage from './pages/UsersPage'

const PAGES: Record<string, ReactNode> = {
  '/': <HomePage />,
  '/users': <UsersPage />,
  '/audit': <AuditPage />,
  '/profile': <ProfilePage />,
  '/patients': <PatientsPage />,
  '/diagnoses': <DiagnosesPage />,
  '/schedule': <SchedulePage />,
  '/my-day': <MyDayPage />,
  '/settings': <SettingsPage />,
  '/tasks': <TasksPage />,
  '/leads': <LeadsPage />,
  '/campaigns': <CampaignsPage />,
  '/reports': <ReportsPage />,
}

// detail pages inherit the roles of their menu section
const DETAIL_ROUTES: { path: string; section: string; element: ReactNode }[] = [
  { path: '/patients/:id', section: '/patients', element: <PatientCardPage /> },
]

function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth()
  const location = useLocation()
  if (status === 'loading') return null
  if (status === 'anonymous') return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}

function Guarded({ item, children }: { item: NavItem; children?: ReactNode }) {
  const { user } = useAuth()
  if (!user || !item.roles.includes(user.role)) return <Navigate to="/" replace />
  return children ?? PAGES[item.path] ?? <SoonPage labelKey={item.labelKey} />
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
          {DETAIL_ROUTES.map((r) => (
            <Route
              key={r.path}
              path={r.path}
              element={<Guarded item={NAV_ITEMS.find((i) => i.path === r.section)!}>{r.element}</Guarded>}
            />
          ))}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
