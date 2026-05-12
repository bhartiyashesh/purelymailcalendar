import type { EventOut } from "../types";
import {
  addDays,
  addMonths,
  addWeeks,
  buildWeekDays,
  fmtMonthYear,
  fmtWeekRange,
  startOfDay,
} from "../util";
import { MonthView } from "./MonthView";
import { WeekView } from "./WeekView";

export type CalendarMode = "month" | "week" | "day";

type Props = {
  events: EventOut[];
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
  onCreateAt: (start: Date, durationMinutes?: number) => void;
  onEdit: (e: EventOut) => void;
  onMove: (e: EventOut, newStart: Date) => void;
  mode: CalendarMode;
  setMode: (m: CalendarMode) => void;
  anchor: Date;
  setAnchor: (d: Date) => void;
};

export function CalendarView({
  events,
  loading,
  error,
  onRefresh,
  onCreateAt,
  onEdit,
  onMove,
  mode,
  setMode,
  anchor,
  setAnchor,
}: Props) {
  const goPrev = () =>
    setAnchor(
      mode === "month"
        ? addMonths(anchor, -1)
        : mode === "week"
        ? addWeeks(anchor, -1)
        : addDays(anchor, -1)
    );
  const goNext = () =>
    setAnchor(
      mode === "month"
        ? addMonths(anchor, 1)
        : mode === "week"
        ? addWeeks(anchor, 1)
        : addDays(anchor, 1)
    );
  const goToday = () => setAnchor(startOfDay(new Date()));

  const heading =
    mode === "month"
      ? fmtMonthYear(anchor)
      : mode === "week"
      ? (() => {
          const wk = buildWeekDays(anchor, 0);
          return fmtWeekRange(wk[0], addDays(wk[0], 6));
        })()
      : new Intl.DateTimeFormat(undefined, {
          weekday: "long",
          month: "long",
          day: "numeric",
          year: "numeric",
        }).format(anchor);

  const openDay = (d: Date) => {
    setAnchor(startOfDay(d));
    setMode("day");
  };

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold text-ink-900">{heading}</h2>
        <div className="ml-1 flex items-center gap-1">
          <button onClick={goPrev} className="btn-secondary px-2" aria-label="previous">‹</button>
          <button onClick={goToday} className="btn-secondary">Today</button>
          <button onClick={goNext} className="btn-secondary px-2" aria-label="next">›</button>
        </div>
        <div className="flex-1" />
        <div className="inline-flex overflow-hidden rounded-md border border-ink-200 bg-white text-sm">
          <button
            onClick={() => setMode("month")}
            className={`px-3 py-1.5 ${mode === "month" ? "bg-accent-600 text-white" : "text-ink-700 hover:bg-ink-50"}`}
          >
            Month
          </button>
          <button
            onClick={() => setMode("week")}
            className={`px-3 py-1.5 ${mode === "week" ? "bg-accent-600 text-white" : "text-ink-700 hover:bg-ink-50"}`}
          >
            Week
          </button>
          <button
            onClick={() => setMode("day")}
            className={`px-3 py-1.5 ${mode === "day" ? "bg-accent-600 text-white" : "text-ink-700 hover:bg-ink-50"}`}
          >
            Day
          </button>
        </div>
        <button onClick={onRefresh} disabled={loading} className="btn-secondary">
          {loading ? "..." : "Refresh"}
        </button>
      </div>

      {error && (
        <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
      )}

      {mode === "month" && (
        <MonthView
          anchorDate={anchor}
          events={events}
          onCreateAt={openDay}
          onEdit={onEdit}
          onMove={onMove}
        />
      )}
      {mode === "week" && (
        <WeekView
          anchorDate={anchor}
          events={events}
          onCreateAt={(start, duration) => onCreateAt(start, duration)}
          onEdit={onEdit}
          onMove={onMove}
        />
      )}
      {mode === "day" && (
        <WeekView
          anchorDate={anchor}
          events={events}
          onCreateAt={(start, duration) => onCreateAt(start, duration)}
          onEdit={onEdit}
          onMove={onMove}
          daysCount={1}
        />
      )}

      <p className="mt-3 text-xs text-ink-500">
        {mode === "month"
          ? "Click a day to open it in day view and pick a time slot. Drag an event to move it."
          : "Click a slot or drag a vertical range to create. Drag an event to move it; you'll be asked to confirm before update emails go out."}
      </p>
    </section>
  );
}
