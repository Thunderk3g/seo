// Tracks which website the user is currently looking at. Persisted in
// localStorage so it survives reloads. Used by Topbar (Add Site / Start crawl)
// and SessionsPage (filter sessions by active site).
//
// `null` means "no site selected yet" — UI should show the Add Site flow.

import { useCallback, useEffect, useState } from 'react';

const STORAGE_KEY = 'lattice.activeSiteId';

function readStored(): string | null {
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    return v && v.length > 0 ? v : null;
  } catch {
    return null;
  }
}

export function useActiveSite(): {
  activeSiteId: string | null;
  setActiveSite: (id: string | null) => void;
} {
  const [activeSiteId, setActiveSiteIdState] = useState<string | null>(readStored);

  // Sync across tabs.
  useEffect(() => {
    function handleStorage(e: StorageEvent) {
      if (e.key === STORAGE_KEY) setActiveSiteIdState(readStored());
    }
    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, []);

  const setActiveSite = useCallback((id: string | null) => {
    try {
      if (id) window.localStorage.setItem(STORAGE_KEY, id);
      else window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // localStorage unavailable (private mode etc.) — fall back to memory.
    }
    setActiveSiteIdState(id);
  }, []);

  return { activeSiteId, setActiveSite };
}
