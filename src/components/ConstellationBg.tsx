/**
 * Decorative constellation backdrop echoing conjur3.com — faint nodes and
 * edges with mint/amber accents. Purely presentational; aria-hidden.
 */
const NODES = [
  { x: 12, y: 22, r: 1.6, c: "var(--color-mint)" },
  { x: 28, y: 48, r: 1.2, c: "var(--color-aqua)" },
  { x: 44, y: 30, r: 2.2, c: "var(--color-amber)" },
  { x: 63, y: 58, r: 1.4, c: "var(--color-mint)" },
  { x: 78, y: 26, r: 1.8, c: "var(--color-aqua)" },
  { x: 88, y: 64, r: 1.2, c: "var(--color-amber)" },
  { x: 54, y: 78, r: 1.5, c: "var(--color-mint)" },
];
const EDGES: [number, number][] = [
  [0, 1],
  [1, 2],
  [2, 4],
  [3, 4],
  [3, 6],
  [4, 5],
];

export function ConstellationBg({ className = "" }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      className={`pointer-events-none absolute inset-0 h-full w-full ${className}`}
    >
      {EDGES.map(([a, b], i) => (
        <line
          key={i}
          x1={NODES[a].x}
          y1={NODES[a].y}
          x2={NODES[b].x}
          y2={NODES[b].y}
          stroke="rgba(115,233,216,0.18)"
          strokeWidth="0.15"
        />
      ))}
      {NODES.map((n, i) => (
        <circle key={i} cx={n.x} cy={n.y} r={n.r * 0.4} fill={n.c} opacity="0.7" />
      ))}
    </svg>
  );
}
