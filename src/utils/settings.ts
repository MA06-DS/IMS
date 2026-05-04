import { useEffect, useState } from 'react'

const KEY = 'iims-settings'
const EVENT_NAME = 'iims-settings-change'

export type AdminSettings = {
  lowStockThreshold: number
  currency: string
  pageSize: number
}

export const defaultAdminSettings: AdminSettings = {
  lowStockThreshold: 15,
  currency: 'USD',
  pageSize: 10,
}

function readSettings(): AdminSettings {
  if (typeof window === 'undefined') return defaultAdminSettings
  try {
    const raw = window.localStorage.getItem(KEY)
    return raw ? { ...defaultAdminSettings, ...(JSON.parse(raw) as Partial<AdminSettings>) } : defaultAdminSettings
  } catch {
    return defaultAdminSettings
  }
}

export function getAdminSettings() {
  return readSettings()
}

export function saveAdminSettings(settings: AdminSettings) {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(KEY, JSON.stringify(settings))
  window.dispatchEvent(new Event(EVENT_NAME))
}

export function useAdminSettings() {
  const [settings, setSettings] = useState<AdminSettings>(() => readSettings())

  useEffect(() => {
    if (typeof window === 'undefined') return undefined

    const sync = () => setSettings(readSettings())
    const onStorage = (event: StorageEvent) => {
      if (event.key === KEY || event.key === null) sync()
    }

    window.addEventListener('storage', onStorage)
    window.addEventListener(EVENT_NAME, sync)

    return () => {
      window.removeEventListener('storage', onStorage)
      window.removeEventListener(EVENT_NAME, sync)
    }
  }, [])

  return settings
}

export function useLowStockThreshold() {
  return useAdminSettings().lowStockThreshold
}
