import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getOrderById } from '@/api/orders.api'
import { formatCurrency, formatDateTime } from '@/utils/format'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { PageHeader } from '@/components/shared/PageHeader'
import { StatusBadge } from '@/components/shared/StatusBadge'

export default function CheckoutSuccessPage() {
  const { id } = useParams()
  const order = useQuery({
    queryKey: ['orders', id],
    queryFn: () => getOrderById(id!),
    enabled: Boolean(id),
  })

  return (
    <div className="space-y-6">
      <PageHeader title="Order placed" description="Thanks for your purchase. Your receipt is below." />
      <Card className="border-line-strong bg-brand-tint/60">
        <CardContent className="space-y-4 p-10 text-center">
          <div className="text-sm text-muted">
            Your order ID is <span className="font-medium text-ink-strong">{id}</span>.
          </div>
          {order.data ? (
            <div className="mx-auto grid max-w-md gap-2 rounded-xl border border-line bg-card p-4 text-left text-sm">
              <div className="flex items-center justify-between">
                <span className="text-muted">Status</span>
                <StatusBadge status={order.data.status} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted">Placed</span>
                <span className="font-medium text-ink-strong">{formatDateTime(order.data.datetime)}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted">Items</span>
                <span className="font-medium text-ink-strong">{order.data.itemCount ?? (order.data.items ?? []).length}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted">Total</span>
                <span className="font-semibold text-ink-strong">{formatCurrency(order.data.totalAmount ?? 0)}</span>
              </div>
            </div>
          ) : null}
          <div className="flex flex-wrap justify-center gap-3">
            <Button asChild>
              <Link to="/app/orders">View orders</Link>
            </Button>
            <Button asChild variant="secondary">
              <Link to="/app/products">Continue shopping</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
