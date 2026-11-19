/** HireCall mark: rounded voice bars, read as a call in progress. */
export function LogoMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 40 40" className={className} aria-hidden="true" fill="currentColor">
      <rect x="3" y="14" width="6" height="12" rx="3" />
      <rect x="12" y="6" width="6" height="28" rx="3" />
      <rect x="21" y="10" width="6" height="20" rx="3" />
      <rect x="30" y="16" width="6" height="8" rx="3" />
    </svg>
  );
}

export function Logo({
  className = "",
  markClassName = "h-8 w-8",
  textClassName = "text-2xl",
}: {
  className?: string;
  markClassName?: string;
  textClassName?: string;
}) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <LogoMark className={markClassName} />
      <span className={`font-display font-semibold tracking-tight ${textClassName}`}>HireCall</span>
    </span>
  );
}
