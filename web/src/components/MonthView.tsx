import { useMemo, useRef, useState } from "react";
import type { EventOut } from "../types";
import {
  addDays,
  buildMonthGrid,
  fmtTimeShort,
  isSameDay,
  isSameMonth,
} from "../util";

type Props = {
  anchorDate: Date;
  events: EventOut[];
  onCreateAt: (day: Date) => void;
  onEdit: (e: EventOut) => void;
  onMove: (e: EventOut, newStart: Date) => void;
};

const WEEK_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

type DragState = {
  event: EventOut;
  pointerId: number;
  fromCellKey: string;
  hoverCellKey: string | null;
};

function dayKey(d: Date) {
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

export function MonthView({ anchorDate, events, onCreateAt, onEdit, onMove }: Props) {
  const grid = useMemo(() => buildMonthGrid(anchorDate, 0), [anchorDate]);
  const today = useMemo(() => new Date(), []);

  const eventsByDay = useMemo(() => {
    const map = new Map<string, EventOut[]>();
    for (const e of events) {
      const start = new Date(e.start);
      const k = dayKey(start);
      if (!map.has(k)) map.set(k, []);
      map.get(k)!.push(e);
    }
    for (const list of map.values()) {
      list.sort((a, b) => +new Date(a.start) - +new Date(b.start));
    }
    return map;
  }, [events]);

  const [drag, setDrag] = useState<DragState | null>(null);
  const cellRefs = useRef(new Map<string, HTMLDivElement>());

  const startDrag = (e: React.PointerEvent, event: EventOut) => {
    e.stopPropagation();
    e.preventDefault();
    const start = new Date(event.start);
    setDrag({
      event,
      pointerId: e.pointerId,
      fromCellKey: dayKey(start),
      hoverCellKey: null,
    });
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag || drag.pointerId !== e.pointerId) return;
    const el = document.elementFromPoint(e.clientX, e.clientY);
    const cell = el?.closest<HTMLElement>("[data-cell-key]");
    const key = cell?.dataset.cellKey || null;
    if (key !== drag.hoverCellKey) {
      setDrag({ ...drag, hoverCellKey: key });
    }
  };

  const onPointerUp = (e: React.PointerEvent) => {
    if (!drag || drag.pointerId !== e.pointerId) return;
    const target = drag.hoverCellKey;
    const fromKey = drag.fromCellKey;
    const ev = drag.event;
    setDrag(null);
    if (!target || target === fromKey) return;
    const [y, m, d] = target.split("-").map(Number);
    const oldStart = new Date(ev.start);
    const newStart = new Date(y, m, d, oldStart.getHours(), oldStart.getMinutes(), 0, 0);
    onMove(ev, newStart);
  };

  return (
    <div
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={() => setDrag(null)}
      className="select-none"
    >
      <div className="grid grid-cols-7 border-l border-t border-ink-200 bg-white text-center text-[11px] font-medium uppercase tracking-wide text-ink-500">
        {WEEK_LABELS.map((l) => (
          <div key={l} className="border-r border-b border-ink-200 px-2 py-1.5">
            {l}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7 grid-rows-6 border-l border-ink-200 bg-white">
        {grid.map((d) => {
          const k = dayKey(d);
          const inMonth = isSameMonth(d, anchorDate);
          const isToday = isSameDay(d, today);
          const items = eventsByDay.get(k) || [];
          const isDropTarget = drag?.hoverCellKey === k && drag.fromCellKey !== k;
          return (
            <div
              key={k}
              data-cell-key={k}
              ref={(el) => {
                if (el) cellRefs.current.set(k, el);
                else cellRefs.current.delete(k);
              }}
              onClick={() => {
                if (drag) return;
                const now = new Date();
                const at = new Date(d);
                if (isSameDay(d, now)) {
                  // Same day: round up to next 15-min slot from now.
                  const nextSlotMin = Math.ceil((now.getHours() * 60 + now.getMinutes() + 1) / 15) * 15;
                  at.setHours(0, nextSlotMin, 0, 0);
                } else {
                  // Different day: default to 9am.
                  at.setHours(9, 0, 0, 0);
                }
                onCreateAt(at);
              }}
              className={[
                "relative flex h-28 flex-col gap-0.5 border-r border-b border-ink-200 px-1.5 py-1 cursor-pointer transition-colors",
                inMonth ? "bg-white" : "bg-ink-50/60 text-ink-400",
                isDropTarget ? "ring-2 ring-inset ring-accent-500" : "",
              ].join(" ")}
            >
              <div className="flex items-center justify-between">
                <span
                  className={[
                    "text-xs font-medium",
                    isToday
                      ? "flex h-5 w-5 items-center justify-center rounded-full bg-accent-600 text-white"
                      : inMonth
                      ? "text-ink-700"
                      : "text-ink-400",
                  ].join(" ")}
                >
                  {d.getDate()}
                </span>
              </div>
              <div className="flex flex-col gap-0.5 overflow-hidden">
                {items.slice(0, 3).map((ev) => {
                  const start = new Date(ev.start);
                  const accepted = ev.attendees.some((a) => a.partstat.toUpperCase() === "ACCEPTED");
                  const declined = ev.attendees.length > 0 && ev.attendees.every((a) => a.partstat.toUpperCase() === "DECLINED");
                  const tone = declined
                    ? "bg-red-50 text-red-700 ring-red-200"
                    : accepted
                    ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                    : "bg-accent-50 text-accent-700 ring-accent-200";
                  return (
                    <button
                      key={ev.occurrence_id || ev.uid}
                      onPointerDown={(e) => startDrag(e, ev)}
                      onClick={(e) => {
                        e.stopPropagation();
                        if (drag) return;
                        onEdit(ev);
                      }}
                      className={`pointer-events-auto truncate rounded px-1.5 py-0.5 text-left text-[11px] font-medium ring-1 ${tone} hover:brightness-95`}
                      title={`${ev.summary} - ${fmtTimeShort(start)}`}
                    >
                      <span className="opacity-70">{fmtTimeShort(start)}</span>{" "}
                      {ev.recurrence && <span aria-hidden="true">↻ </span>}
                      <span className="truncate">{ev.summary || "(untitled)"}</span>
                    </button>
                  );
                })}
                {items.length > 3 && (
                  <span className="text-[10px] font-medium text-ink-500">+{items.length - 3} more</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
