export function fmtDateTime(iso: string, tz?: string | null): string {
  const d = new Date(iso);
  const opts: Intl.DateTimeFormatOptions = {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: tz || undefined,
  };
  return new Intl.DateTimeFormat(undefined, opts).format(d);
}

export function fmtRange(startIso: string, endIso: string, tz?: string | null): string {
  const start = new Date(startIso);
  const end = new Date(endIso);
  const dateOpts: Intl.DateTimeFormatOptions = {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: tz || undefined,
  };
  const timeOpts: Intl.DateTimeFormatOptions = {
    hour: "numeric",
    minute: "2-digit",
    timeZone: tz || undefined,
  };
  const datePart = new Intl.DateTimeFormat(undefined, dateOpts).format(start);
  const startTime = new Intl.DateTimeFormat(undefined, timeOpts).format(start);
  const endTime = new Intl.DateTimeFormat(undefined, timeOpts).format(end);
  return `${datePart} · ${startTime} - ${endTime}${tz ? ` ${tz}` : ""}`;
}

export function partstatStyle(p: string): string {
  const s = (p || "").toUpperCase();
  if (s === "ACCEPTED") return "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200";
  if (s === "DECLINED") return "bg-red-50 text-red-700 ring-1 ring-red-200";
  if (s === "TENTATIVE") return "bg-amber-50 text-amber-700 ring-1 ring-amber-200";
  if (s === "DELEGATED") return "bg-sky-50 text-sky-700 ring-1 ring-sky-200";
  return "bg-ink-100 text-ink-600 ring-1 ring-ink-200";
}

export function toLocalIsoMinute(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function startOfDay(d: Date): Date {
  const r = new Date(d);
  r.setHours(0, 0, 0, 0);
  return r;
}

export function startOfMonth(d: Date): Date {
  const r = startOfDay(d);
  r.setDate(1);
  return r;
}

export function startOfWeek(d: Date, weekStartsOn = 0): Date {
  const r = startOfDay(d);
  const day = r.getDay();
  const diff = (day - weekStartsOn + 7) % 7;
  r.setDate(r.getDate() - diff);
  return r;
}

export function addDays(d: Date, n: number): Date {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}

export function addMonths(d: Date, n: number): Date {
  const r = new Date(d);
  r.setMonth(r.getMonth() + n);
  return r;
}

export function addWeeks(d: Date, n: number): Date {
  return addDays(d, n * 7);
}

export function addMinutes(d: Date, n: number): Date {
  return new Date(d.getTime() + n * 60000);
}

export function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

export function isSameMonth(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth();
}

export function buildMonthGrid(monthAnchor: Date, weekStartsOn = 0): Date[] {
  const first = startOfMonth(monthAnchor);
  const gridStart = startOfWeek(first, weekStartsOn);
  return Array.from({ length: 42 }, (_, i) => addDays(gridStart, i));
}

export function buildWeekDays(anchor: Date, weekStartsOn = 0): Date[] {
  const start = startOfWeek(anchor, weekStartsOn);
  return Array.from({ length: 7 }, (_, i) => addDays(start, i));
}

export function minutesFromStartOfDay(d: Date): number {
  return d.getHours() * 60 + d.getMinutes();
}

export function fmtMonthYear(d: Date): string {
  return new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" }).format(d);
}

export function fmtWeekRange(start: Date, end: Date): string {
  const a = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(start);
  const b = new Intl.DateTimeFormat(undefined, {
    month: start.getMonth() === end.getMonth() ? undefined : "short",
    day: "numeric",
    year: "numeric",
  }).format(end);
  return `${a} - ${b}`;
}

export function fmtTimeShort(d: Date): string {
  return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(d);
}
