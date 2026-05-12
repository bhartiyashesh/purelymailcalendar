import { useEffect, useMemo, useRef, useState } from "react";
import type { EventOut } from "../types";
import {
  addMinutes,
  buildWeekDays,
  fmtTimeShort,
  isSameDay,
  minutesFromStartOfDay,
} from "../util";

type Props = {
  anchorDate: Date;
  events: EventOut[];
  onCreateAt: (start: Date, durationMinutes: number) => void;
  onEdit: (e: EventOut) => void;
  onMove: (e: EventOut, newStart: Date) => void;
  daysCount?: 1 | 7;
};

const HOUR_PX = 48;
const SLOT_MIN = 15;
const SLOT_PX = (HOUR_PX * SLOT_MIN) / 60;
const TOTAL_PX = HOUR_PX * 24;

type SelectionDrag = {
  kind: "select";
  pointerId: number;
  dayIndex: number;
  startMin: number;
  endMin: number;
};

type EventDrag = {
  kind: "event";
  pointerId: number;
  event: EventOut;
  durationMin: number;
  hoverDayIndex: number | null;
  hoverStartMin: number | null;
};

type Drag = SelectionDrag | EventDrag | null;

type LaneInfo = {
  ev: EventOut;
  topPx: number;
  heightPx: number;
  lane: number;
  laneCount: number;
};

function snapToSlot(min: number): number {
  return Math.max(0, Math.min(24 * 60, Math.round(min / SLOT_MIN) * SLOT_MIN));
}

function eventTone(ev: EventOut): string {
  const declined = ev.attendees.length > 0 && ev.attendees.every((a) => a.partstat.toUpperCase() === "DECLINED");
  const accepted = ev.attendees.some((a) => a.partstat.toUpperCase() === "ACCEPTED");
  if (declined) return "bg-red-100/90 text-red-900 ring-red-300";
  if (accepted) return "bg-emerald-100/90 text-emerald-900 ring-emerald-300";
  return "bg-accent-100/90 text-accent-900 ring-accent-300";
}

function assignLanes(items: { ev: EventOut; startMin: number; endMin: number }[]): LaneInfo[] {
  const sorted = [...items].sort((a, b) => a.startMin - b.startMin || a.endMin - b.endMin);
  const lanes: number[] = []; // lane index -> end minute of last event
  const out: LaneInfo[] = [];
  for (const it of sorted) {
    let lane = lanes.findIndex((endMin) => endMin <= it.startMin);
    if (lane === -1) {
      lane = lanes.length;
      lanes.push(it.endMin);
    } else {
      lanes[lane] = it.endMin;
    }
    out.push({
      ev: it.ev,
      lane,
      laneCount: 0,
      topPx: (it.startMin / 60) * HOUR_PX,
      heightPx: Math.max(SLOT_PX, ((it.endMin - it.startMin) / 60) * HOUR_PX),
    });
  }
  const laneCount = lanes.length || 1;
  return out.map((l) => ({ ...l, laneCount }));
}

export function WeekView({ anchorDate, events, onCreateAt, onEdit, onMove, daysCount = 7 }: Props) {
  const days = useMemo(
    () => (daysCount === 1 ? [new Date(anchorDate)] : buildWeekDays(anchorDate, 0)),
    [anchorDate, daysCount]
  );
  const [now, setNow] = useState<Date>(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);
  const today = now;
  const nowMin = minutesFromStartOfDay(now);
  const todayIdx = useMemo(() => days.findIndex((d) => isSameDay(d, now)), [days, now]);

  const scrollRef = useRef<HTMLDivElement>(null);
  const didScrollRef = useRef(false);
  useEffect(() => {
    if (didScrollRef.current) return;
    const el = scrollRef.current;
    if (!el) return;
    const target = (nowMin / 60) * HOUR_PX - el.clientHeight / 3;
    el.scrollTop = Math.max(0, target);
    didScrollRef.current = true;
  }, [nowMin]);

  const eventsByDay = useMemo(() => {
    const map: { ev: EventOut; startMin: number; endMin: number }[][] = days.map(() => []);
    for (const e of events) {
      const start = new Date(e.start);
      const end = new Date(e.end);
      for (let i = 0; i < days.length; i++) {
        if (isSameDay(start, days[i])) {
          map[i].push({
            ev: e,
            startMin: minutesFromStartOfDay(start),
            endMin: Math.min(24 * 60, minutesFromStartOfDay(start) + Math.round((+end - +start) / 60000)),
          });
        }
      }
    }
    return map.map(assignLanes);
  }, [days, events]);

  const bodyRef = useRef<HTMLDivElement>(null);
  const colRefs = useRef<HTMLDivElement[]>([]);
  const [drag, setDrag] = useState<Drag>(null);

  const minutesAt = (clientY: number, colEl: HTMLElement) => {
    const rect = colEl.getBoundingClientRect();
    const y = clientY - rect.top;
    return snapToSlot((y / HOUR_PX) * 60);
  };

  const dayIndexFor = (target: HTMLElement | null) => {
    const col = target?.closest<HTMLElement>("[data-day-index]");
    if (!col) return null;
    return Number(col.dataset.dayIndex);
  };

  const onColPointerDown = (e: React.PointerEvent, dayIndex: number) => {
    if ((e.target as HTMLElement).closest("[data-event]")) return;
    e.preventDefault();
    const colEl = colRefs.current[dayIndex];
    const startMin = minutesAt(e.clientY, colEl);
    setDrag({
      kind: "select",
      pointerId: e.pointerId,
      dayIndex,
      startMin,
      endMin: startMin + SLOT_MIN,
    });
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };

  const onEventPointerDown = (e: React.PointerEvent, ev: EventOut) => {
    e.stopPropagation();
    e.preventDefault();
    const start = new Date(ev.start);
    const end = new Date(ev.end);
    setDrag({
      kind: "event",
      pointerId: e.pointerId,
      event: ev,
      durationMin: Math.max(15, Math.round((+end - +start) / 60000)),
      hoverDayIndex: null,
      hoverStartMin: null,
    });
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };

  useEffect(() => {
    if (!drag) return;
    const handleMove = (e: PointerEvent) => {
      if (drag.pointerId !== e.pointerId) return;
      if (drag.kind === "select") {
        const colEl = colRefs.current[drag.dayIndex];
        if (!colEl) return;
        const m = minutesAt(e.clientY, colEl);
        setDrag({ ...drag, endMin: m });
      } else if (drag.kind === "event") {
        const target = document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null;
        const idx = dayIndexFor(target);
        if (idx == null) {
          if (drag.hoverDayIndex != null) setDrag({ ...drag, hoverDayIndex: null, hoverStartMin: null });
          return;
        }
        const colEl = colRefs.current[idx];
        const startMin = minutesAt(e.clientY, colEl);
        if (drag.hoverDayIndex !== idx || drag.hoverStartMin !== startMin) {
          setDrag({ ...drag, hoverDayIndex: idx, hoverStartMin: startMin });
        }
      }
    };
    const handleUp = (e: PointerEvent) => {
      if (drag.pointerId !== e.pointerId) return;
      if (drag.kind === "select") {
        const a = Math.min(drag.startMin, drag.endMin);
        const b = Math.max(drag.startMin, drag.endMin);
        const duration = Math.max(SLOT_MIN, b - a);
        const day = days[drag.dayIndex];
        const start = new Date(day);
        start.setHours(0, Math.round(a), 0, 0);
        setDrag(null);
        onCreateAt(start, duration);
      } else if (drag.kind === "event") {
        const idx = drag.hoverDayIndex;
        const startMin = drag.hoverStartMin;
        const ev = drag.event;
        setDrag(null);
        if (idx == null || startMin == null) return;
        const day = days[idx];
        const newStart = new Date(day);
        newStart.setHours(0, Math.round(startMin), 0, 0);
        const oldStart = new Date(ev.start);
        if (
          isSameDay(oldStart, newStart) &&
          minutesFromStartOfDay(oldStart) === minutesFromStartOfDay(newStart)
        ) {
          return;
        }
        onMove(ev, newStart);
      }
    };
    const handleCancel = () => setDrag(null);
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
    window.addEventListener("pointercancel", handleCancel);
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
      window.removeEventListener("pointercancel", handleCancel);
    };
  }, [drag, days, onCreateAt, onMove]);

  const selectionRect = (() => {
    if (!drag || drag.kind !== "select") return null;
    const a = Math.min(drag.startMin, drag.endMin);
    const b = Math.max(drag.startMin, drag.endMin);
    const top = (a / 60) * HOUR_PX;
    const height = Math.max(SLOT_PX, ((b - a) / 60) * HOUR_PX);
    return { dayIndex: drag.dayIndex, top, height, label: `${minutesToLabel(a)} - ${minutesToLabel(b)}` };
  })();

  const moveGhost = (() => {
    if (!drag || drag.kind !== "event" || drag.hoverDayIndex == null || drag.hoverStartMin == null) return null;
    const top = (drag.hoverStartMin / 60) * HOUR_PX;
    const height = Math.max(SLOT_PX, (drag.durationMin / 60) * HOUR_PX);
    return { dayIndex: drag.hoverDayIndex, top, height };
  })();

  const gridTemplate = `64px repeat(${daysCount}, minmax(0, 1fr))`;
  return (
    <div className="overflow-hidden rounded-lg border border-ink-200 bg-white">
      <div className="grid border-b border-ink-200 text-center text-xs" style={{ gridTemplateColumns: gridTemplate }}>
        <div />
        {days.map((d) => {
          const isToday = isSameDay(d, today);
          return (
            <div
              key={+d}
              className={`px-2 py-2 ${isToday ? "bg-accent-50/40" : ""}`}
            >
              <div className="text-[10px] font-medium uppercase tracking-wide text-ink-500">
                {new Intl.DateTimeFormat(undefined, { weekday: "short" }).format(d)}
              </div>
              <div
                className={
                  isToday
                    ? "mx-auto mt-0.5 flex h-6 w-6 items-center justify-center rounded-full bg-accent-600 text-xs font-semibold text-white"
                    : "text-sm font-medium text-ink-800"
                }
              >
                {d.getDate()}
              </div>
            </div>
          );
        })}
      </div>
      <div ref={scrollRef} className="relative max-h-[70vh] overflow-y-auto">
        <div ref={bodyRef} className="relative grid" style={{ height: TOTAL_PX, gridTemplateColumns: gridTemplate }}>
          <div className="relative border-r border-ink-200">
            {Array.from({ length: 24 }, (_, h) => (
              <div
                key={h}
                className="absolute left-0 right-0 border-b border-ink-100 pr-1 text-right text-[10px] uppercase tracking-wide text-ink-400"
                style={{ top: h * HOUR_PX, height: HOUR_PX }}
              >
                {h === 0 ? "" : labelFromHour(h)}
              </div>
            ))}
            <div
              className="absolute right-0 -translate-y-1/2 rounded-sm bg-red-500 px-1 text-[9px] font-semibold uppercase tracking-wide text-white"
              style={{ top: (nowMin / 60) * HOUR_PX }}
            >
              {fmtTimeShort(now)}
            </div>
          </div>
          {days.map((d, di) => (
            <div
              key={+d}
              ref={(el) => {
                if (el) colRefs.current[di] = el;
              }}
              data-day-index={di}
              onPointerDown={(e) => onColPointerDown(e, di)}
              className="relative border-r border-ink-200"
            >
              {Array.from({ length: 24 }, (_, h) => (
                <div
                  key={h}
                  className="absolute left-0 right-0 border-b border-ink-100"
                  style={{ top: h * HOUR_PX, height: HOUR_PX }}
                />
              ))}
              {eventsByDay[di].map(({ ev, topPx, heightPx, lane, laneCount }) => {
                const widthPct = 100 / laneCount;
                const leftPct = lane * widthPct;
                const isDragging = drag?.kind === "event" && drag.event.uid === ev.uid;
                return (
                  <button
                    key={ev.uid}
                    data-event
                    onPointerDown={(e) => onEventPointerDown(e, ev)}
                    onClick={(e) => {
                      e.stopPropagation();
                      if (drag) return;
                      onEdit(ev);
                    }}
                    className={`absolute m-[1px] overflow-hidden rounded px-1.5 py-1 text-left text-[11px] font-medium ring-1 ${eventTone(
                      ev
                    )} ${isDragging ? "opacity-40" : "hover:brightness-95"}`}
                    style={{
                      top: topPx,
                      height: heightPx,
                      left: `${leftPct}%`,
                      width: `calc(${widthPct}% - 2px)`,
                    }}
                    title={ev.summary}
                  >
                    <div className="truncate">{ev.summary || "(untitled)"}</div>
                    <div className="opacity-70">{fmtTimeShort(new Date(ev.start))}</div>
                  </button>
                );
              })}
              {selectionRect?.dayIndex === di && (
                <div
                  className="pointer-events-none absolute left-0 right-0 m-[1px] flex items-end justify-end rounded bg-accent-500/15 px-1.5 py-0.5 text-[11px] font-medium text-accent-700 ring-1 ring-accent-400"
                  style={{ top: selectionRect.top, height: selectionRect.height }}
                >
                  {selectionRect.label}
                </div>
              )}
              {moveGhost?.dayIndex === di && (
                <div
                  className="pointer-events-none absolute left-0 right-0 m-[1px] rounded bg-accent-500/20 ring-1 ring-accent-500"
                  style={{ top: moveGhost.top, height: moveGhost.height }}
                />
              )}
              {todayIdx === di && (
                <>
                  <div
                    className="pointer-events-none absolute left-0 right-0 h-px bg-red-500"
                    style={{ top: (nowMin / 60) * HOUR_PX }}
                  />
                  <div
                    className="pointer-events-none absolute -ml-[5px] -translate-y-1/2 h-2.5 w-2.5 rounded-full bg-red-500 ring-2 ring-white"
                    style={{ top: (nowMin / 60) * HOUR_PX, left: 0 }}
                  />
                </>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function labelFromHour(h: number): string {
  const dt = new Date();
  dt.setHours(h, 0, 0, 0);
  return new Intl.DateTimeFormat(undefined, { hour: "numeric" }).format(dt);
}

function minutesToLabel(m: number): string {
  const d = new Date();
  d.setHours(0, m, 0, 0);
  return fmtTimeShort(d);
}
