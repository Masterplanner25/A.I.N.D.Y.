// "3 h 10 m" / "45 m": directing minutes, read at a glance.
export function fmtMinutes(minutes) {
  const total = Math.round(Number(minutes) || 0);
  const h = Math.floor(total / 60);
  const m = total % 60;
  return h ? `${h} h ${m} m` : `${m} m`;
}

// The line under Focus quality (DIRECTING_TIME_SPEC §5): shown only when there are prompts. Not in the score.
export function directingNote(summary) {
  const totals = summary?.totals;
  if (!totals || !(totals.prompts > 0)) return null;
  const n = totals.sessions;
  return `Directing agents: ${fmtMinutes(totals.directing_minutes)} over ${n} session${n === 1 ? "" : "s"} in the last ${summary.days} days (not in the score).`;
}
