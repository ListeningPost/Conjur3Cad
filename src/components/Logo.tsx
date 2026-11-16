import Link from "next/link";

/**
 * Conjur3 wordmark. "CONJUR" in the mono wordmark face with a mint "3",
 * echoing the site header. `mark` renders just the glyph badge.
 */
export function Logo({
  href = "/",
  className = "",
}: {
  href?: string | null;
  className?: string;
}) {
  const inner = (
    <span className={`wordmark inline-flex items-baseline text-lg ${className}`}>
      <LogoMark className="mr-2 h-5 w-5 translate-y-1" />
      <span className="text-paper">CONJUR</span>
      <span className="text-mint">3</span>
    </span>
  );
  if (href === null) return inner;
  return (
    <Link href={href} aria-label="Conjur3 home">
      {inner}
    </Link>
  );
}

/** The angular "C3" badge mark. */
export function LogoMark({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <path
        d="M16 2 L29 9.5 V22.5 L16 30 L3 22.5 V9.5 Z"
        fill="none"
        stroke="var(--color-mint)"
        strokeWidth="1.6"
        opacity="0.5"
      />
      <path
        d="M16 9 L23 13 V21 L16 25 L9 21 V13 Z"
        fill="none"
        stroke="var(--color-aqua)"
        strokeWidth="1.6"
      />
      <circle cx="16" cy="17" r="2" fill="var(--color-mint)" />
    </svg>
  );
}
