import { useEffect, useRef, useState } from "react";
import { api } from "../api";

export function VerifyView({ onDone }: { onDone: () => void }) {
  const [status, setStatus] = useState<"working" | "ok" | "err">("working");
  const [err, setErr] = useState<string | null>(null);

  // Keep onDone in a ref so the effect that calls api.verifyLink only depends
  // on mount, not on the parent re-rendering with a fresh inline arrow. Without
  // this, the verify endpoint gets hit twice — first call succeeds, second
  // call sees the token already used and briefly flashes "Sign-in failed".
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    const params = new URLSearchParams(window.location.search);
    const token = params.get("token") || "";
    if (!token) {
      setStatus("err");
      setErr("No token in URL.");
      return;
    }
    api
      .verifyLink(token)
      .then(() => {
        setStatus("ok");
        window.history.replaceState({}, "", "/");
        setTimeout(() => onDoneRef.current(), 400);
      })
      .catch((e) => {
        setStatus("err");
        setErr(e?.message || "verify failed");
      });
  }, []);

  return (
    <div className="flex min-h-full items-center justify-center px-4 py-12">
      <div className="card w-full max-w-md p-6 text-center">
        {status === "working" && (
          <>
            <h2 className="text-lg font-semibold text-ink-900">Signing you in…</h2>
            <p className="mt-1 text-sm text-ink-600">Verifying your link.</p>
          </>
        )}
        {status === "ok" && (
          <>
            <h2 className="text-lg font-semibold text-emerald-700">You're in.</h2>
            <p className="mt-1 text-sm text-ink-600">Redirecting…</p>
          </>
        )}
        {status === "err" && (
          <>
            <h2 className="text-lg font-semibold text-red-700">Sign-in failed</h2>
            <p className="mt-1 text-sm text-ink-600">{err}</p>
            <a href="/login" className="btn-primary mt-4 inline-flex">Back to sign in</a>
          </>
        )}
      </div>
    </div>
  );
}
