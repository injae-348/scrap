import { createBrowserRouter, RouterProvider, type RouteObject } from 'react-router'
import { AppLayout } from './components/AppLayout'
import { BrowsePage } from './pages/BrowsePage'
import { LoginPage } from './pages/LoginPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { ScrapDetailPage } from './pages/ScrapDetailPage'
import { ScrapEditorPage } from './pages/ScrapEditorPage'
import { SearchPage } from './pages/SearchPage'
import { SettingsPage } from './pages/SettingsPage'
import { SetupPage } from './pages/SetupPage'
import { TotpResetPage } from './pages/TotpResetPage'

// 목록류 화면 아래에 붙는 상세·편집 패널 (데스크톱: 오른쪽 패널 / 모바일: 전체 화면)
const panelRoutes: RouteObject[] = [
  { path: 'scraps/new', element: <ScrapEditorPage /> },
  { path: 'scraps/:id', element: <ScrapDetailPage /> },
  { path: 'scraps/:id/edit', element: <ScrapEditorPage /> },
]

const router = createBrowserRouter([
  { path: '/setup', element: <SetupPage /> },
  { path: '/login', element: <LoginPage /> },
  {
    element: <AppLayout />,
    children: [
      { path: '/', element: <BrowsePage view="all" />, children: panelRoutes },
      { path: '/liked', element: <BrowsePage key="liked" view="liked" />, children: panelRoutes },
      { path: '/due', element: <BrowsePage key="due" view="due" />, children: panelRoutes },
      { path: '/search', element: <SearchPage />, children: panelRoutes.filter((r) => r.path !== 'scraps/new') },
      { path: '/settings', element: <SettingsPage /> },
      { path: '/settings/totp', element: <TotpResetPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])

export function App() {
  return <RouterProvider router={router} />
}
