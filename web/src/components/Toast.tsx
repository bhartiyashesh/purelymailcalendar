import { useEffect } from "react";

export type ToastKind = "success" | "error" | "info";
export type ToastMsg = { id: number; kind: ToastKind; text: string };

export function Toast({ toast, onDismiss }: { toast: ToastMsg; onDismiss: (id: number) => void }) {
  useEffect(() => {
    const t = setTimeout(() => onDismiss(toast.id), 5000);
    return () => clearTimeout(t);
  }, [toast.id, onDismiss]);
  const styles =
    toast.kind === "success"
      ? "bg-emerald-50 text-emerald-800 ring-emerald-200"
      : toast.kind === "error"
      ? "bg-red-50 text-red-800 ring-red-200"
      : "bg-ink-50 text-ink-800 ring-ink-200";
  return (
    <div
      className={`pointer-events-auto rounded-md px-3 py-2 text-sm shadow-md ring-1 ${styles}`}
      role="status"
    >
      <div className="flex items-start gap-3">
        <span className="flex-1 whitespace-pre-wrap">{toast.text}</span>
        <button
          aria-label="dismiss"
          className="text-current/60 hover:text-current"
          onClick={() => onDismiss(toast.id)}
        >
          ×
        </button>
      </div>
    </div>
  );
}

export function ToastStack({ toasts, onDismiss }: { toasts: ToastMsg[]; onDismiss: (id: number) => void }) {
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2">
      {toasts.map((t) => (
        <Toast key={t.id} toast={t} onDismiss={onDismiss} />
      ))}
    </div>
  );
}
