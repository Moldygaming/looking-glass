export function Logo({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <defs>
        <linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#2ee6c7" />
          <stop offset="100%" stopColor="#7cf0de" />
        </linearGradient>
      </defs>
      <rect x="3" y="3" width="26" height="26" rx="7" fill="none" stroke="url(#lg)" strokeWidth="1.5" />
      <circle cx="16" cy="16" r="6" fill="none" stroke="url(#lg)" strokeWidth="1.5" />
      <circle cx="16" cy="16" r="2" fill="#2ee6c7" />
      <path d="M16 4v4M16 24v4M4 16h4M24 16h4" stroke="#2ee6c7" strokeWidth="1.2" opacity="0.7" />
    </svg>
  );
}
