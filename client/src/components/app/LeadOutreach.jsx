import { useCallback, useEffect, useState } from "react";
import {
  executeLeadActions,
  listLeadActions,
  listLeads,
  previewLeadActions,
  revertLeadAction,
  setLeadContact,
} from "../../api/search.js";
import { safeMap } from "../../utils/safe";

// Saved leads, their hand-entered contact, and the outreach actions taken on them.
//
// This is the client face of the Search Execution Layer, which was API-only until 2026-09-16.
// Two rules the server enforces and the UI only reflects:
//   * the email channel sends ONLY to a lead with a contact you typed here — discovery never
//     sets one — and only when the server's AINDY_SEARCH_OUTREACH_SEND gate is on; a lead
//     without a contact comes back `queued`, and the note says why.
//   * a `sent` action cannot be reverted (outreach can't be un-sent), so no Revert is offered.

const STATUS_COLOR = {
  drafted: "#4dabf7",
  queued: "#ffda5f",
  sent: "#51cf66",
  failed: "#ff6b6b",
  reverted: "#868e96",
};

function fmt(ts) {
  if (!ts) return "";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return String(ts);
  }
}

function ContactCell({ lead, onSaved }) {
  // Keyed on the saved contact by the parent (`key={...}`), so a server-side change re-mounts
  // the cell with a fresh initial value instead of an effect mirroring the prop into state.
  const [value, setValue] = useState(lead.contact_email || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  async function save(next) {
    setSaving(true);
    setError(null);
    try {
      const out = await setLeadContact(lead.id, next);
      onSaved(lead.id, out?.contact_email ?? (next || null));
    } catch (err) {
      setError(err?.message || "Could not save contact");
    }
    setSaving(false);
  }

  return (
    <div className="contact-cell">
      <input
        className="text-input contact-input"
        type="email"
        value={value}
        placeholder="contact email (typed by you)"
        aria-label={`Contact for ${lead.company}`}
        onChange={(e) => setValue(e.target.value)}
        disabled={saving}
      />
      <button className="small-button" disabled={saving || value === (lead.contact_email || "")} onClick={() => save(value.trim())}>
        Save
      </button>
      {lead.contact_email && (
        <button className="small-button ghost" disabled={saving} onClick={() => save("")}>
          Clear
        </button>
      )}
      {error && <span className="cell-error">{error}</span>}
    </div>
  );
}

export default function LeadOutreach({ refreshToken = 0, showToast }) {
  const [leads, setLeads] = useState([]);
  const [actions, setActions] = useState([]);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState(null);

  const fetchAll = useCallback(
    () => Promise.all([listLeads(), listLeadActions(20)]).then(([leadRows, actionRows]) => ({
      leads: Array.isArray(leadRows) ? leadRows : leadRows?.leads || [],
      actions: actionRows?.actions || [],
    })),
    [],
  );

  const load = useCallback(async () => {
    try {
      const next = await fetchAll();
      setLeads(next.leads);
      setActions(next.actions);
      setLoadError(null);
    } catch (err) {
      setLoadError(err?.message || "Could not load leads");
    }
  }, [fetchAll]);

  useEffect(() => {
    // Fetch on mount and whenever the parent bumps `refreshToken` (a search just saved rows).
    // A result that lands after unmount is dropped.
    let alive = true;
    fetchAll()
      .then((next) => {
        if (!alive) return;
        setLeads(next.leads);
        setActions(next.actions);
        setLoadError(null);
      })
      .catch((err) => {
        if (alive) setLoadError(err?.message || "Could not load leads");
      });
    return () => {
      alive = false;
    };
  }, [fetchAll, refreshToken]);

  function contactSaved(leadId, contactEmail) {
    setLeads((rows) => safeMap(rows, (r) => (r.id === leadId ? { ...r, contact_email: contactEmail } : r)));
    showToast?.(contactEmail ? `Contact saved for lead ${leadId}` : `Contact cleared for lead ${leadId}`);
  }

  async function run(fn, label) {
    setBusy(true);
    try {
      const out = await fn();
      return out;
    } catch (err) {
      showToast?.(err?.message || `${label} failed`);
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function handlePreview() {
    const out = await run(previewLeadActions, "Preview");
    if (out) setPreview(out);
  }

  async function handleExecute(channel) {
    if (channel === "email") {
      const withContact = leads.filter((l) => l.contact_email).length;
      const ok = window.confirm(
        `Send outreach email now?\n\nThis delivers to leads that have a contact (${withContact} of ${leads.length}) ` +
          "if the server's send gate is on. A sent email cannot be reverted.",
      );
      if (!ok) return;
    }
    const out = await run(() => executeLeadActions(channel), "Outreach");
    if (!out) return;
    const counts = {};
    for (const a of out.actions || []) counts[a.status] = (counts[a.status] || 0) + 1;
    const summary = safeMap(Object.entries(counts), ([k, v]) => `${v} ${k}`).join(", ");
    showToast?.(out.status === "no_action" ? "No lead cleared the gate." : `Outreach: ${summary}`);
    setPreview(null);
    await load();
  }

  async function handleRevert(actionId) {
    const out = await run(() => revertLeadAction(actionId), "Revert");
    if (!out) return;
    if (out.status === "sent_cannot_revert") {
      showToast?.("That outreach was sent — it cannot be reverted.");
    } else {
      showToast?.(`Action ${actionId}: ${out.status}`);
    }
    await load();
  }

  return (
    <section className="outreach-section" aria-label="Saved leads and outreach">
      <style>{`
        .outreach-section { margin-top: 30px; }
        .outreach-section h2 { color: #fff; font-size: 18px; margin: 0 0 12px 0; }
        .outreach-table { width: 100%; border-collapse: collapse; font-size: 13px; color: #ccc; }
        .outreach-table th { text-align: left; color: #888; font-weight: normal; padding: 6px 8px; border-bottom: 1px solid #222; }
        .outreach-table td { padding: 8px; border-bottom: 1px solid #1c1c1c; vertical-align: top; }
        .contact-cell { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
        .contact-input { padding: 6px 8px; min-width: 220px; }
        .small-button { padding: 6px 10px; background: #2b2f33; color: #fff; border: 1px solid #333; border-radius: 4px; cursor: pointer; font-size: 12px; }
        .small-button:disabled { opacity: 0.5; cursor: not-allowed; }
        .small-button.ghost { background: transparent; }
        .small-button.danger { background: #3a1f1f; border-color: #5a2a2a; }
        .cell-error { color: #ff6b6b; font-size: 12px; }
        .outreach-controls { display: flex; gap: 8px; margin: 12px 0; flex-wrap: wrap; }
        .status-pill { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; font-weight: bold; color: #111; }
        .preview-box { background: #141414; border: 1px solid #222; border-radius: 8px; padding: 12px; margin: 10px 0; font-size: 13px; color: #ccc; }
        .note { color: #888; font-size: 12px; }
      `}</style>

      <h2>Saved leads</h2>
      {loadError && <p className="cell-error">{loadError}</p>}
      {leads.length === 0 ? (
        <p className="empty-text">No saved leads yet — a lead search saves its results here.</p>
      ) : (
        <table className="outreach-table">
          <thead>
            <tr>
              <th>Company</th>
              <th>Score</th>
              <th>Contact</th>
            </tr>
          </thead>
          <tbody>
            {safeMap(leads, (lead) => (
              <tr key={lead.id}>
                <td>
                  <strong style={{ color: "#4dabf7" }}>{lead.company}</strong>
                  {lead.url && (
                    <div className="note">
                      <a href={lead.url} target="_blank" rel="noreferrer" style={{ color: "#888" }}>
                        {lead.url}
                      </a>
                    </div>
                  )}
                </td>
                <td>{lead.search_score ?? lead.overall_score ?? "—"}</td>
                <td>
                  <ContactCell key={`${lead.id}:${lead.contact_email || ""}`} lead={lead} onSaved={contactSaved} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2 style={{ marginTop: 24 }}>Outreach</h2>
      <p className="note">
        Draft never contacts anyone. Email sends only to leads with a contact you entered above, and only when the
        server&apos;s send gate is on — otherwise the action is queued, and its note says why.
      </p>
      <div className="outreach-controls">
        <button className="small-button" disabled={busy} onClick={handlePreview}>
          Preview gate
        </button>
        <button className="small-button" disabled={busy} onClick={() => handleExecute("draft")}>
          Draft outreach
        </button>
        <button className="small-button danger" disabled={busy} onClick={() => handleExecute("email")}>
          Send email
        </button>
      </div>

      {preview && (
        <div className="preview-box" aria-label="Gate preview">
          <div>
            <strong>Would action:</strong>{" "}
            {preview.selected?.length ? safeMap(preview.selected, (s) => s.company).join(", ") : "nothing"}
          </div>
          {preview.skipped?.length > 0 && (
            <div style={{ marginTop: 6 }}>
              <strong>Gated out:</strong>
              <ul style={{ margin: "4px 0 0 18px" }}>
                {safeMap(preview.skipped, (s, i) => (
                  <li key={i}>
                    {s.company} — {s.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      <h2 style={{ marginTop: 24 }}>Actions</h2>
      {actions.length === 0 ? (
        <p className="empty-text">No outreach actions yet.</p>
      ) : (
        <table className="outreach-table">
          <thead>
            <tr>
              <th>Company</th>
              <th>Channel</th>
              <th>Status</th>
              <th>Detail</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {safeMap(actions, (a) => (
              <tr key={a.id}>
                <td>
                  <strong>{a.company}</strong>
                  {a.draft_subject && <div className="note">{a.draft_subject}</div>}
                </td>
                <td>{a.channel}</td>
                <td>
                  <span className="status-pill" style={{ background: STATUS_COLOR[a.status] || "#ccc" }}>
                    {a.status}
                  </span>
                </td>
                <td className="note">
                  {a.status === "sent" && a.recipient && (
                    <div>
                      to {a.recipient} · {fmt(a.sent_at)}
                    </div>
                  )}
                  {a.note && <div>{a.note}</div>}
                </td>
                <td>
                  {a.status !== "sent" && a.status !== "reverted" && (
                    <button className="small-button ghost" disabled={busy} onClick={() => handleRevert(a.id)}>
                      Revert
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
