import { Nav } from "@/components/Nav";
import { Logo } from "@/components/Logo";
import { ButtonLink } from "@/components/Button";
import { ConstellationBg } from "@/components/ConstellationBg";
import { ModelSlideshow } from "@/components/ModelSlideshow";
import { GitHubButton, GitHubNavLink } from "@/components/GitHubLink";
import { REPO_URL } from "@/lib/site";

const MODEL_SLIDES = [
  { src: "/models/01-iso-board.png", label: "Case + board · iso" },
  { src: "/models/02-iso-ports.png", label: "Port side · iso" },
  { src: "/models/03-top.png", label: "Top view" },
  { src: "/models/04-side.png", label: "Side elevation" },
  { src: "/models/05-section.png", label: "Section view" },
];

const PROPERTIES = [
  {
    n: "01",
    tag: "Plain English → Assembly",
    title: "From a sentence to a solid model.",
    body: "Describe the part in plain English. Conjur3 returns a real, multi-part assembly — feature trees, sketches, expressions, mates — native to your CAD package. Not a mesh that looks right. A model that machines.",
  },
  {
    n: "02",
    tag: "Iterative",
    title: "Treat designs like code.",
    body: "Tweak, refactor, and branch your ideas the way engineers work in a codebase. Drive variants by editing parameters — version history, not re-prompting — so every revision is intentional and reversible.",
  },
  {
    n: "03",
    tag: "Model-agnostic",
    title: "Bring your own model.",
    body: "Works with Claude Code, Hermes, OpenCode, and any capable model — from Claude Opus to the leading open-source Chinese models. No lock-in to one vendor's brain. Point Conjur3 at whatever you already trust.",
  },
  {
    n: "04",
    tag: "Unmetered",
    title: "Buy a seat. Sit at the table.",
    body: "We sell a premium MCP so we can build full-time — and so can you. That's why we don't meter you by the token the way the incumbents do. One seat, all in. We're builders too.",
  },
];

export default function Home() {
  return (
    <div className="min-h-screen">
      <Nav />

      {/* Hero */}
      <section className="relative overflow-hidden border-b border-white/10">
        <div className="bg-grid absolute inset-0 opacity-60" />
        <ConstellationBg className="opacity-70" />
        <div className="relative mx-auto max-w-6xl px-5 py-24 md:py-32">
          <a
            href={REPO_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="mb-6 inline-flex items-center gap-2 rounded-full border border-mint/40 bg-mint/10 px-4 py-1.5 font-mono text-[0.7rem] uppercase tracking-wider text-mint transition-colors hover:bg-mint/20"
          >
            Open source<span className="hidden sm:inline"> · MIT licensed</span> · View the code →
          </a>
          <p className="kicker mb-6">Autonomous parametric CAD</p>
          <h1 className="display max-w-4xl text-5xl text-paper md:text-7xl">
            Engineering
            <br />
            <span className="text-gradient">on demand.</span>
          </h1>
          <p className="mt-8 max-w-2xl text-lg leading-relaxed text-white/70">
            Conjur3 is an autonomous design agent that operates a parametric CAD
            kernel directly. It produces real, multi-part assemblies — feature
            trees, sketches, expressions — that machine, fit, and hold
            tolerance. Not pretty geometry. Engineering output.
          </p>
          <div className="mt-10 flex flex-wrap items-center gap-4">
            <ButtonLink href="/signup">Get access →</ButtonLink>
            <GitHubButton />
            <ButtonLink href="/signin" variant="ghost">
              Sign in
            </ButtonLink>
          </div>
          <div className="mt-12 flex flex-wrap gap-x-8 gap-y-2 font-mono text-[0.7rem] uppercase tracking-wider text-white/40">
            <span>Parametric STEP output</span>
            <span>OCCT kernel</span>
            <span>On-prem capable</span>
            <span>MIT licensed</span>
          </div>
        </div>
      </section>

      {/* Model showcase */}
      <section className="mx-auto max-w-6xl px-5 py-20">
        <div className="mb-10 max-w-3xl">
          <p className="kicker mb-3">Built with Conjur3</p>
          <h2 className="display text-3xl text-paper md:text-4xl">
            Real parts. Real assemblies.
          </h2>
          <p className="mt-4 text-white/60">
            A Raspberry Pi 4 enclosure — board, standoffs, fasteners, and a
            snap-fit shell, mated into one parametric assembly that fits,
            clears, and holds tolerance. The artistic render beside the actual
            CAD model.
          </p>
        </div>

        <div className="grid items-start gap-6 lg:grid-cols-2">
          {/* Artistic render (low-bitrate background video) */}
          <figure className="relative overflow-hidden rounded-[var(--radius-card)] bg-ink">
            <div className="relative aspect-video w-full">
              <video
                className="absolute inset-0 h-full w-full object-cover"
                poster="/media/rpi-assembly-poster.jpg"
                autoPlay
                loop
                muted
                playsInline
                preload="metadata"
                aria-label="Artistic orbiting render of a Raspberry Pi 4 enclosure built by a Conjur3 agent"
              >
                {/* Mobile gets the lighter encode; desktop the 720p */}
                <source
                  src="/media/rpi-assembly-orbit-mobile.mp4"
                  type="video/mp4"
                  media="(max-width: 768px)"
                />
                <source src="/media/rpi-assembly-orbit.mp4" type="video/mp4" />
              </video>
              {/* Soft dark vignette corners */}
              <div
                className="pointer-events-none absolute inset-0 rounded-[var(--radius-card)]"
                style={{ boxShadow: "inset 0 0 100px 32px var(--color-ink)" }}
              />
              {/* Floating ARTISTIC RENDER label, all white */}
              <span className="absolute right-4 top-4 font-mono text-[0.6rem] uppercase tracking-[0.2em] text-white">
                * Artistic render
              </span>
            </div>
          </figure>

          {/* Actual CAD model slideshow */}
          <ModelSlideshow slides={MODEL_SLIDES} />
        </div>

        <p className="mt-6 max-w-3xl text-xs leading-relaxed text-white/40">
          <span className="text-mint">*</span> Using our premium AI Skill MCP,
          this agent became capable of not only building a Raspberry Pi case —
          it downloaded the exact model of the exact Pi we wanted a case for,
          built the case to specification, and sourced the screws to purchase.
        </p>
      </section>

      {/* What's different */}
      <section className="mx-auto max-w-6xl px-5 pb-20">
        <p className="kicker mb-3">Why Conjur3</p>
        <h2 className="display max-w-3xl text-3xl text-paper md:text-4xl">
          Built different. On purpose.
        </h2>
        <div className="mt-12 grid gap-5 md:grid-cols-2">
          {PROPERTIES.map((p) => (
            <div
              key={p.n}
              className="rounded-[var(--radius-card)] border border-white/10 bg-ink-2/60 p-7 transition-colors hover:border-mint/40"
            >
              <div className="flex items-center gap-3 font-mono text-xs uppercase tracking-wider text-white/40">
                <span className="text-mint">{p.n}</span>
                <span>· {p.tag}</span>
              </div>
              <h3 className="display mt-4 text-xl text-paper">{p.title}</h3>
              <p className="mt-3 text-sm leading-relaxed text-white/60">
                {p.body}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* CTA band */}
      <section className="relative overflow-hidden border-y border-white/10 bg-ink-2/40">
        <ConstellationBg className="opacity-40" />
        <div className="relative mx-auto flex max-w-6xl flex-col items-start gap-6 px-5 py-16 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="kicker mb-3">Team access</p>
            <h2 className="display text-3xl text-paper md:text-4xl">
              Claim your seat.
            </h2>
            <p className="mt-3 max-w-xl text-sm text-white/60">
              Your organization manages access by seat. Create an org, invite
              your engineers with license keys, and put Conjur3 to work.
            </p>
          </div>
          <div className="flex flex-wrap gap-4">
            <ButtonLink href="/signup">Get access →</ButtonLink>
            <ButtonLink href="/claim" variant="outline">
              Claim a key
            </ButtonLink>
            <GitHubButton />
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="mx-auto max-w-6xl px-5 py-12">
        <div className="flex flex-col items-start justify-between gap-4 border-t border-white/10 pt-8 md:flex-row md:items-center">
          <Logo href={null} />
          <GitHubNavLink />
          <p className="font-mono text-[0.7rem] uppercase tracking-wider text-white/30">
            © {new Date().getFullYear()} Conjur3 · MIT licensed · Autonomous
            parametric CAD
          </p>
        </div>
      </footer>
    </div>
  );
}
