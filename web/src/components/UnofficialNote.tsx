export function UnofficialNote({ className = "" }: { className?: string }) {
  return (
    <p className={`text-xs text-ink-500 ${className}`}>
      Purelymail Calendar is an unofficial, community-built tool. It is not affiliated with, endorsed by, or sponsored by Purelymail. Made by{" "}
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
