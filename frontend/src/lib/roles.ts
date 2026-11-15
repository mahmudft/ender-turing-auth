import { redirect } from "@tanstack/react-router"

import { type UserPublic, type UserRole, UsersService } from "@/client"

type MaybeUser = Pick<UserPublic, "role"> | null | undefined

export const ROLES: UserRole[] = ["admin", "manager", "member"]

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: "Admin",
  manager: "Manager",
  member: "Member",
}

// Mirrors the backend rules; the backend remains the source of truth.
export const canViewUsers = (user: MaybeUser) =>
  user?.role === "admin" || user?.role === "manager"

export const canManageUsers = (user: MaybeUser) => user?.role === "admin"

// Route guard for beforeLoad: fetch the current user fresh from the API so a
// role change is respected on the next navigation, and send users without
// access back to the dashboard instead of rendering a page full of 403s.
export async function requireAccess(check: (user: MaybeUser) => boolean) {
  const { data: user } = await UsersService.readUserMe()
  if (!check(user)) {
    throw redirect({ to: "/" })
  }
}
