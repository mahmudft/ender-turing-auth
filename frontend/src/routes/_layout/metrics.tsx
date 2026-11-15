import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"

import { MetricsService } from "@/client"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { canViewUsers, ROLE_LABELS, ROLES, requireAccess } from "@/lib/roles"

export const Route = createFileRoute("/_layout/metrics")({
  component: Metrics,
  beforeLoad: () => requireAccess(canViewUsers),
  head: () => ({
    meta: [{ title: "Metrics - FastAPI Template" }],
  }),
})

function Stat({ label, value }: { label: string; value?: number }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent className="text-3xl font-bold">{value ?? "–"}</CardContent>
    </Card>
  )
}

function Metrics() {
  const { data } = useQuery({
    queryKey: ["metrics"],
    queryFn: async () => (await MetricsService.readMetrics()).data,
  })

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Metrics</h1>
        <p className="text-muted-foreground">Users and items at a glance</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Total users" value={data?.total_users} />
        <Stat label="Active users" value={data?.active_users} />
        <Stat label="Total items" value={data?.total_items} />
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        {ROLES.map((role) => (
          <Stat
            key={role}
            label={`${ROLE_LABELS[role]}s`}
            value={data?.users_by_role[role] ?? 0}
          />
        ))}
      </div>
    </div>
  )
}
