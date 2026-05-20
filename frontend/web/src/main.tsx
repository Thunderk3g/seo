import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import './styles/lattice.css';
import './styles/crawler-console.css';
// Tailwind imported LAST so its utility classes win specificity on
// elements that opt in (every shadcn primitive). preflight is off so
// no global reset hits legacy pages.
import './styles/tailwind.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Conservative defaults; per-hook tuning happens in src/api/hooks/* (Day 1+).
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>
);
