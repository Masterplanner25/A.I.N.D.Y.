// Effort is stored in hours because that is what the math wants — the MasterPlan ETA projects
// `remaining_effort` in hours, WCU is hours × complexity × difficulty, the Infinity Volume axis
// sums hours. It is not the unit a person estimates in. "About five weeks" was being typed as
// 201.75 by the owner doing the conversion in their head, which is the wrong place for it.
//
// The basis is a declared working calendar, not the wall clock: 8h day, 5-day week, and a
// month of ~21.7 working days (260 / 12). A "month" of effort is a month of working, not 730
// hours of it.

export const HOURS_PER_DAY = 8;
export const HOURS_PER_WEEK = HOURS_PER_DAY * 5;
export const HOURS_PER_MONTH = HOURS_PER_DAY * (260 / 12);   // 173.33

export const EFFORT_UNITS = [
  { key: "hours", label: "hours", hours: 1 },
  { key: "days", label: "days", hours: HOURS_PER_DAY },
  { key: "weeks", label: "weeks", hours: HOURS_PER_WEEK },
  { key: "months", label: "months", hours: HOURS_PER_MONTH },
];

const BY_KEY = {};
for (const u of EFFORT_UNITS) BY_KEY[u.key] = u;

export function toHours(amount, unit) {
  const n = Number.parseFloat(amount);
  const u = BY_KEY[unit] || BY_KEY.hours;
  if (!Number.isFinite(n)) return NaN;
  return Math.round(n * u.hours * 100) / 100;
}

// The largest unit that reads as a whole-ish number: 200h → "1.2 mo", 12h → "1.5 d",
// 3h → "3h". Below one day it stays in hours, because "0.4 d" helps nobody.
export function describeHours(hours) {
  const h = Number(hours);
  if (!Number.isFinite(h) || h <= 0) return null;
  if (h >= HOURS_PER_MONTH) return `${trim(h / HOURS_PER_MONTH)} mo`;
  if (h >= HOURS_PER_WEEK) return `${trim(h / HOURS_PER_WEEK)} wk`;
  if (h >= HOURS_PER_DAY) return `${trim(h / HOURS_PER_DAY)} d`;
  return `${trim(h)}h`;
}

function trim(n) {
  return Number.isInteger(n) ? String(n) : n.toFixed(1).replace(/\.0$/, "");
}
