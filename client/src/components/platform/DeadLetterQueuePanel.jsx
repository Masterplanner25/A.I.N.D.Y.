import React, { useCallback, useEffect, useState } from "react";

import {
  getQueueHealth,
  getDeadLetters,
  replayDeadLetter,
  deleteDeadLetter,
  drainDeadLetters,
} from "../../api/operator.js";
import { Toast } from "../shared/Toast";
import { useToast } from "../../utils/useToast";
import { safeMap } from "../../utils/safe";
import {
  ActionButton,
  EmptyState,
  ErrorState,
  formatCompactNumber,
  formatDateTime,
  InlineBadge,
  LoadingState,
  MetricCard,
  SurfaceGrid,
  SurfacePanel,
  surfacePalette,
} from "./SurfacePrimitives";

// The Dead-Letter Queue is a record you can now act on: replay a job back onto the queue,
// delete one permanently, or drain the whole DLQ. (Walk-log item 29 — control plane.)
export default function DeadLetterQueuePanel() {
  const [health, setHealth] = useState(null);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState(null); // job_id currently being acted on
  const [confirmDeleteId, setConfirmDeleteId] = useState(null);
  const [confirmDrain, setConfirmDrain] = useState(false);
  const { toast, showToast, clearToast } = useToast();

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [h, dl] = await Promise.all([
        getQueueHealth().catch(() => null),
        getDeadLetters(100),
      ]);
      setHealth(h);
      setItems(Array.isArray(dl?.items) ? dl.items : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load the dead-letter queue.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleReplay = async (jobId) => {
    setBusyId(jobId);
    try {
      await replayDeadLetter(jobId);
      showToast("Job replayed onto the queue.");
      await load();
    } catch (err) {
      showToast(err?.message || "Replay failed.");
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (jobId) => {
    setBusyId(jobId);
    setConfirmDeleteId(null);
    try {
      await deleteDeadLetter(jobId);
      showToast("Dead-letter job deleted.");
      await load();
    } catch (err) {
      showToast(err?.message || "Delete failed.");
    } finally {
      setBusyId(null);
    }
  };

  const handleDrain = async () => {
    setConfirmDrain(false);
    setBusyId("__drain__");
    try {
      const res = await drainDeadLetters();
      showToast(`Drained ${res?.drained ?? 0} job${res?.drained === 1 ? "" : "s"} from the DLQ.`);
      await load();
    } catch (err) {
      showToast(err?.message || "Drain failed.");
    } finally {
      setBusyId(null);
    }
  };

  const metrics = health?.metrics || {};
  const draining = busyId === "__drain__";

  const drainAction = items.length > 0
    ? (confirmDrain
        ? (
          <div className="flex items-center gap-2">
            <span className="text-xs" style={{ color: surfacePalette.muted }}>Drain all {items.length}?</span>
            <ActionButton tone="danger" onClick={handleDrain} disabled={draining}>
              {draining ? "Draining…" : "Confirm"}
            </ActionButton>
            <ActionButton tone="ghost" onClick={() => setConfirmDrain(false)} disabled={draining}>Cancel</ActionButton>
          </div>
        )
        : <ActionButton tone="danger" onClick={() => setConfirmDrain(true)}>Drain DLQ</ActionButton>)
    : null;

  return (
    <SurfaceGrid>
      <div className="lg:col-span-12">
        <SurfacePanel
          title="Dead-Letter Queue"
          subtitle="Jobs that exhausted their retries. Replay one back onto the queue, delete it, or drain the queue."
          actions={
            <div className="flex items-center gap-2">
              {drainAction}
              <ActionButton tone="ghost" onClick={load} disabled={loading}>Refresh</ActionButton>
            </div>
          }
        >
          {/* Queue health metrics */}
          {health ? (
            <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
              <MetricCard label="DLQ Depth" value={formatCompactNumber(metrics.dlq_depth || 0)} tone={(metrics.dlq_depth || 0) > 0 ? "warning" : "success"} />
              <MetricCard label="Queue Depth" value={formatCompactNumber(metrics.queue_depth || 0)} tone="info" />
              <MetricCard label="In-Flight" value={formatCompactNumber(metrics.in_flight_count || 0)} tone="info" />
              <MetricCard
                label="Backend"
                value={String(health.backend_name || health.backend || "—")}
                hint={health.degraded ? "degraded" : "healthy"}
                tone={health.degraded ? "danger" : "success"}
              />
            </div>
          ) : null}

          {loading ? <LoadingState label="Loading dead-letter queue" /> : null}
          {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}

          {!loading && !error && items.length === 0 ? (
            <EmptyState title="Dead-letter queue is empty" description="Jobs that exhaust their retries will appear here, ready to replay or clear." />
          ) : null}

          {!loading && !error && items.length > 0 ? (
            <div className="space-y-3">
              {safeMap(items, (item, i) => {
                const jobId = item?.job_id || item?.idempotency_key || String(i);
                const retry = item?.retry_metadata || {};
                const busy = busyId === jobId;
                return (
                  <div
                    key={jobId}
                    className="flex flex-col gap-3 rounded-[18px] border px-4 py-3 md:flex-row md:items-center md:justify-between"
                    style={{ borderColor: surfacePalette.border }}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <InlineBadge tone="warning">{item?.task_name || "unknown task"}</InlineBadge>
                        <InlineBadge>{jobId}</InlineBadge>
                        {retry.attempt_count != null ? (
                          <InlineBadge tone="danger">
                            {retry.attempt_count}/{retry.max_attempts ?? "?"} attempts
                          </InlineBadge>
                        ) : null}
                      </div>
                      {item?.enqueued_at ? (
                        <div className="mt-1 text-xs" style={{ color: surfacePalette.muted }}>
                          enqueued {formatDateTime(item.enqueued_at)}
                        </div>
                      ) : null}
                    </div>
                    <div className="flex items-center gap-2">
                      <ActionButton tone="primary" onClick={() => handleReplay(jobId)} disabled={busy}>
                        {busy ? "…" : "Replay"}
                      </ActionButton>
                      {confirmDeleteId === jobId ? (
                        <>
                          <ActionButton tone="danger" onClick={() => handleDelete(jobId)} disabled={busy}>Confirm</ActionButton>
                          <ActionButton tone="ghost" onClick={() => setConfirmDeleteId(null)} disabled={busy}>Cancel</ActionButton>
                        </>
                      ) : (
                        <ActionButton tone="ghost" onClick={() => setConfirmDeleteId(jobId)} disabled={busy}>Delete</ActionButton>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : null}
        </SurfacePanel>
      </div>
      <Toast toast={toast} onDismiss={clearToast} />
    </SurfaceGrid>
  );
}
