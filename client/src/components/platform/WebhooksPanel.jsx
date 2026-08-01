import React, { useCallback, useEffect, useState } from "react";

import { getWebhooks, createWebhook, deleteWebhook } from "../../api/operator.js";
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

// Webhooks — create/list/delete outbound event subscriptions. POST /webhooks + DELETE were
// unwired (walk-log item 29); this is the control-plane surface for them.
export default function WebhooksPanel() {
  const { isAdmin } = useAuth();
  if (!isAdmin) return <AdminAccessRequired />;
  return <WebhooksContent />;
}

const inputStyle = {
  background: "#0d1117",
  border: `1px solid ${surfacePalette.border}`,
  borderRadius: 8,
  color: surfacePalette.text,
  fontSize: 13,
  padding: "9px 12px",
  outline: "none",
  width: "100%",
  boxSizing: "border-box",
};

function WebhooksContent() {
  const [webhooks, setWebhooks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [eventType, setEventType] = useState("");
  const [callbackUrl, setCallbackUrl] = useState("");
  const [secret, setSecret] = useState("");
  const [creating, setCreating] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const [confirmId, setConfirmId] = useState(null);
  const { toast, showToast, clearToast } = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getWebhooks();
      setWebhooks(Array.isArray(res?.webhooks) ? res.webhooks : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load webhooks.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async () => {
    if (!eventType.trim() || !callbackUrl.trim()) {
      showToast("Event type and callback URL are required.");
      return;
    }
    setCreating(true);
    try {
      await createWebhook({ event_type: eventType.trim(), callback_url: callbackUrl.trim(), secret: secret.trim() || undefined });
      showToast("Webhook subscription created.");
      setEventType("");
      setCallbackUrl("");
      setSecret("");
      await load();
    } catch (err) {
      showToast(err?.message || "Create failed.");
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id) => {
    setConfirmId(null);
    setBusyId(id);
    try {
      await deleteWebhook(id);
      showToast("Webhook subscription deleted.");
      await load();
    } catch (err) {
      showToast(err?.message || "Delete failed.");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <PageShell
      eyebrow="Integrations"
      title="Webhooks"
      description="Outbound event subscriptions. Register a callback URL for an event type; the platform posts to it when that event fires."
      actions={<ActionButton tone="ghost" onClick={load} disabled={loading}>Refresh</ActionButton>}
    >
      <SurfaceGrid>
        {/* Create form */}
        <div className="lg:col-span-12">
          <SurfacePanel title="New subscription" subtitle="event_type and callback_url are required; an optional secret signs deliveries.">
            <div className="grid gap-3 md:grid-cols-3">
              <input style={inputStyle} placeholder="event_type (e.g. task.completed)" value={eventType} onChange={(e) => setEventType(e.target.value)} />
              <input style={inputStyle} placeholder="callback_url (https://…)" value={callbackUrl} onChange={(e) => setCallbackUrl(e.target.value)} />
              <input style={inputStyle} placeholder="secret (optional)" value={secret} onChange={(e) => setSecret(e.target.value)} />
            </div>
            <div className="mt-3">
              <ActionButton tone="primary" onClick={handleCreate} disabled={creating}>
                {creating ? "Creating…" : "Create subscription"}
              </ActionButton>
            </div>
          </SurfacePanel>
        </div>

        {/* List */}
        <div className="lg:col-span-12">
          <SurfacePanel title="Subscriptions" subtitle={`${webhooks.length} active`}>
            {loading ? <LoadingState label="Loading webhooks" /> : null}
            {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
            {!loading && !error && webhooks.length === 0 ? (
              <EmptyState title="No webhook subscriptions" description="Create one above to receive outbound events." />
            ) : null}

            {!loading && !error && webhooks.length > 0 ? (
              <div className="space-y-3">
                {safeMap(webhooks, (w, i) => {
                  const id = w?.id || w?.subscription_id || String(i);
                  const busy = busyId === id;
                  return (
                    <div
                      key={id}
                      className="flex flex-col gap-3 rounded-[18px] border px-4 py-3 md:flex-row md:items-center md:justify-between"
                      style={{ borderColor: surfacePalette.border }}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <InlineBadge tone="info">{w?.event_type || "—"}</InlineBadge>
                          {w?.signed ? <InlineBadge tone="success">signed</InlineBadge> : null}
                          {(w?.delivery_failures ?? 0) > 0 ? <InlineBadge tone="danger">{w.delivery_failures} failed</InlineBadge> : null}
                        </div>
                        <div className="mt-1 truncate text-sm" style={{ color: surfacePalette.text }}>{w?.callback_url}</div>
                        <div className="mt-1 text-xs" style={{ color: surfacePalette.muted }}>
                          {w?.created_at ? `created ${formatDateTime(w.created_at)}` : ""}
                          {w?.delivery_successes != null ? ` · ${w.delivery_successes} delivered` : ""}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        {confirmId === id ? (
                          <>
                            <ActionButton tone="danger" onClick={() => handleDelete(id)} disabled={busy}>{busy ? "Deleting…" : "Confirm"}</ActionButton>
                            <ActionButton tone="ghost" onClick={() => setConfirmId(null)} disabled={busy}>Cancel</ActionButton>
                          </>
                        ) : (
                          <ActionButton tone="ghost" onClick={() => setConfirmId(id)} disabled={busy}>Delete</ActionButton>
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
