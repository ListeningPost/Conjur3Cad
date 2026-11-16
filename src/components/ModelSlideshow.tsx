"use client";
import { useCallback, useEffect, useState } from "react";
import Image from "next/image";

export interface ModelSlide {
  src: string;
  label: string;
}

const INTERVAL = 3000;

/**
 * Auto-advancing crossfade slideshow of the actual CAD model captures.
 * Self-contained tile: matches the render's 4:3 frame + soft dark vignette.
 */
export function ModelSlideshow({ slides }: { slides: ModelSlide[] }) {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);

  const go = useCallback(
    (n: number) => setIndex((p) => (n + slides.length) % slides.length),
    [slides.length],
  );

  useEffect(() => {
    if (paused) return;
    const t = setInterval(() => go(index + 1), INTERVAL);
    return () => clearInterval(t);
  }, [index, paused, go]);

  return (
    <div
      className="relative"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      <div className="relative aspect-[4/3] w-full overflow-hidden rounded-[var(--radius-card)] bg-ink">
        {slides.map((s, i) => (
          <Image
            key={s.src}
            src={s.src}
            alt={s.label}
            fill
            sizes="(max-width: 1024px) 100vw, 560px"
            className={`object-contain transition-opacity duration-700 ease-in-out ${
              i === index ? "opacity-100" : "opacity-0"
            }`}
          />
        ))}

        {/* Soft dark vignette corners */}
        <div
          className="pointer-events-none absolute inset-0 rounded-[var(--radius-card)]"
          style={{ boxShadow: "inset 0 0 90px 28px var(--color-ink)" }}
        />

        {/* Corner label */}
        <span className="absolute left-4 top-4 font-mono text-[0.6rem] uppercase tracking-[0.2em] text-white/80">
          Actual model
        </span>

        {/* Caption */}
        <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-center gap-2 p-4 font-mono text-[0.62rem] uppercase tracking-wider">
          <span className="text-mint">
            {String(index + 1).padStart(2, "0")}/{String(slides.length).padStart(2, "0")}
          </span>
          <span className="text-white/55">{slides[index].label}</span>
        </div>

        {/* Prev / next */}
        <button
          aria-label="Previous view"
          onClick={() => go(index - 1)}
          className="absolute left-2 top-1/2 -translate-y-1/2 rounded-full border border-white/15 bg-ink/50 px-2.5 py-1.5 text-sm text-paper backdrop-blur transition-colors hover:border-mint hover:text-mint"
        >
          ←
        </button>
        <button
          aria-label="Next view"
          onClick={() => go(index + 1)}
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full border border-white/15 bg-ink/50 px-2.5 py-1.5 text-sm text-paper backdrop-blur transition-colors hover:border-mint hover:text-mint"
        >
          →
        </button>
      </div>

      {/* Dots */}
      <div className="mt-3 flex items-center justify-center gap-2">
        {slides.map((s, i) => (
          <button
            key={s.src}
            aria-label={`View ${i + 1}`}
            onClick={() => setIndex(i)}
            className={`h-1.5 rounded-full transition-all ${
              i === index ? "w-7 bg-mint" : "w-2.5 bg-white/20 hover:bg-white/40"
            }`}
          />
        ))}
      </div>
    </div>
  );
}
