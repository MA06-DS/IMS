import { useState } from 'react'
import { PageHeader } from '@/components/shared/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { toast } from 'sonner'
import { defaultAdminSettings, saveAdminSettings, type AdminSettings } from '@/utils/settings'

export default function AdminSettingsPage() {
  const [settings, setSettings] = useState<AdminSettings>(() => {
    try {
      const raw = localStorage.getItem('iims-settings')
      return raw ? { ...defaultAdminSettings, ...(JSON.parse(raw) as Partial<AdminSettings>) } : defaultAdminSettings
    } catch {
      return defaultAdminSettings
    }
  })

  return (
    <div className="space-y-6">
      <PageHeader title="Settings" description="Profile + system preferences (UI only)." />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="border-b border-line bg-page">
            <CardTitle>System settings</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label>Low stock threshold</Label>
              <Input
                type="number"
                value={settings.lowStockThreshold}
                onChange={(e) => setSettings((s) => ({ ...s, lowStockThreshold: Number(e.target.value) }))}
              />
            </div>
            <div className="space-y-2">
              <Label>Default currency</Label>
              <Input value={settings.currency} onChange={(e) => setSettings((s) => ({ ...s, currency: e.target.value }))} />
            </div>
            <div className="space-y-2">
              <Label>Pagination size</Label>
              <Input
                type="number"
                value={settings.pageSize}
                onChange={(e) => setSettings((s) => ({ ...s, pageSize: Number(e.target.value) }))}
              />
            </div>
            <Button
              onClick={() => {
                saveAdminSettings(settings)
                toast.success('Settings saved')
              }}
            >
              Save settings
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="border-b border-line bg-page">
            <CardTitle>Notifications</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted">
            Notification preferences are stubbed in the frontend. Backend + messaging provider can wire real alerts later.
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
