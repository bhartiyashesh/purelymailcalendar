type Props = {
  className?: string;
  /**
   * "footer"  - the small line that lives at the bottom of any page (default).
   * "banner"  - a prominent amber callout shown on auth-adjacent pages
   *             so users can't possibly miss that this isn't Purelymail.
   */
  variant?: "footer" | "banner";
};

export function UnofficialNote({ className = "", variant = "footer" }: Props) {
  if (variant === "banner") {
    return (
      <div
        role="note"
        className={`flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs leading-snug text-amber-900 ${className}`}
      >
        <span aria-hidden="true" className="mt-0.5 inline-block h-2 w-2 shrink-0 rounded-full bg-amber-500" />
        <div>
          <strong className="font-semibold">Not affiliated with Purelymail.</strong>{" "}
          This is a community-built tool by{" "}
          <a
            href="https://yasheshbharti.com"
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-amber-900 underline underline-offset-2 hover:text-amber-950"
          >
            Yashesh Bharti
          </a>
          . Source on{" "}
          <a
            href="https://github.com/bhartiyashesh/purelymailcalendar"
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-amber-900 underline underline-offset-2 hover:text-amber-950"
          >
            GitHub
          </a>
          . Verify the running build at{" "}
          <a
            href="/api/version"
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-amber-900 underline underline-offset-2 hover:text-amber-950"
          >
            /api/version
          </a>
          .
        </div>
      </div>
    );
  }
  return (
    <p className={`text-xs text-ink-500 ${className}`}>
      <strong className="font-semibold text-ink-700">Not affiliated with Purelymail.</strong>{" "}
      Community-built tool by{" "}
      <a
        href="https://yasheshbharti.com"
        target="_blank"
        rel="noopener noreferrer"
        className="font-medium text-ink-700 underline-offset-2 hover:text-accent-700 hover:underline"
      >
        Yashesh Bharti
      </a>
      .{" "}
      <a
        href="https://github.com/bhartiyashesh/purelymailcalendar"
        target="_blank"
        rel="noopener noreferrer"
        className="font-medium text-ink-700 underline-offset-2 hover:text-accent-700 hover:underline"
      >
        Source on GitHub
      </a>
      .
    </p>
  );
}
