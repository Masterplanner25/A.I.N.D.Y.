import React, { useCallback, useEffect, useState } from "react";

import { getAdminUsers, promoteUser } from "../../api/operator.js";
import { useAuth } from "../../context/AuthContext";
import { AdminAccessRequired } from "../shared/AdminApiErrorBoundary";
import { Toast } from "../shared/Toast";
import { useToast } from "../../utils/useToast";
import { safeMap } from "../../utils/safe";
import {
  ActionButton,
  EmptyState,
  ErrorState,
  formatDateTime,
  InlineBadge,
  LoadingState,
  PageShell,
  SurfaceGrid,
  SurfacePanel,
  surfacePalette,
} from "./SurfacePrimitives";

// Admin users — the only route that grants admin (POST .../promote) had no UI, so a second
// admin could only be made with a direct DB UPDATE. This panel closes that gap. (Item 29.)
// NB: the *first* admin still needs a DB bootstrap — tracked as FR-6.
export default function AdminUsers() {
  const { isAdmin } = useAuth();
  if (!isAdmin) return <AdminAccessRequired />;
  return <AdminUsersContent />;
}

function AdminUsersContent() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState(null);
  const [confirmId, setConfirmId] = useState(null);
  const { toast, showToast, clearToast } = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getAdminUsers();
      setUsers(Array.isArray(res?.users) ? res.users : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load users.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handlePromote = async (userId) => {
    setConfirmId(null);
    setBusyId(userId);
    try {
      await promoteUser(userId);
      showToast("User promoted to admin.");
      await load();
    } catch (err) {
      showToast(err?.message || "Promotion failed.");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <PageShell
      eyebrow="Access Control"
      title="Admin Users"
      description="Grant platform admin privileges. The only route that promotes a user previously had no UI, so a second admin required a direct database edit."
      actions={<ActionButton tone="ghost" onClick={load} disabled={loading}>Refresh</ActionButton>}
    >
      <SurfaceGrid>
        <div className="lg:col-span-12">
          <SurfacePanel title="Users" subtitle={`${users.length} account${users.length === 1 ? "" : "s"}`}>
            {loading ? <LoadingState label="Loading users" /> : null}
            {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
            {!loading && !error && users.length === 0 ? (
              <EmptyState title="No users" description="Registered accounts will appear here." />
            ) : null}

            {!loading && !error && users.length > 0 ? (
              <div className="space-y-3">
                {safeMap(users, (u) => {
                  const busy = busyId === u.id;
                  return (
                    <div
                      key={u.id}
                      className="flex flex-col gap-3 rounded-[18px] border px-4 py-3 md:flex-row md:items-center md:justify-between"
                      style={{ borderColor: surfacePalette.border }}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm" style={{ color: surfacePalette.text }}>{u.email}</span>
                          {u.is_admin ? <InlineBadge tone="success">admin</InlineBadge> : null}
                          {u.is_active === false ? <InlineBadge tone="danger">inactive</InlineBadge> : null}
                        </div>
                        <div className="mt-1 text-xs" style={{ color: surfacePalette.muted }}>
                          {u.id}{u.created_at ? ` · joined ${formatDateTime(u.created_at)}` : ""}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        {u.is_admin ? (
                          <span className="text-xs" style={{ color: surfacePalette.muted }}>—</span>
                        ) : confirmId === u.id ? (
                          <>
                            <ActionButton tone="primary" onClick={() => handlePromote(u.id)} disabled={busy}>
                              {busy ? "Promoting…" : "Confirm promote"}
                            </ActionButton>
                            <ActionButton tone="ghost" onClick={() => setConfirmId(null)} disabled={busy}>Cancel</ActionButton>
                          </>
                        ) : (
                          <ActionButton tone="primary" onClick={() => setConfirmId(u.id)} disabled={busy}>Promote to admin</ActionButton>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : null}
          </SurfacePanel>
        </div>
      </SurfaceGrid>
      <Toast toast={toast} onDismiss={clearToast} />
    </PageShell>
  );
}
