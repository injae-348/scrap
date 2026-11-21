import { QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { UpdatePrompt } from './components/UpdatePrompt'
import { createQueryClient } from './hooks/queries'
import './index.css'

const queryClient = createQueryClient()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
      <UpdatePrompt />
    </QueryClientProvider>
  </StrictMode>,
)
