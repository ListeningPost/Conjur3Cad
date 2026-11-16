import type { ReactNode } from "react";
import { Logo } from "@/components/Logo";
import { ConstellationBg } from "@/components/ConstellationBg";
import { Card } from "@/components/ui";
import { GitHubNavLink } from "@/components/GitHubLink";

/** Centered card layout used by the auth + onboarding flows. */
export function AuthShell({
  kicker,
  title,
  subtitle,
  children,
  footer,
}: {
  kicker?: string;
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden px-5 py-12">
      <div className="bg-grid absolute inset-0 opacity-40" />
      <ConstellationBg className="opacity-50" />
      <div className="relative w-full max-w-md">
        <div className="mb-8 flex justify-center">
          <Logo />
        </div>
        <Card className="p-8">
          {kicker ? <p className="kicker mb-2">{kicker}</p> : null}
          <h1 className="display text-3xl text-paper">{title}</h1>
          {subtitle ? (
            <p className="mt-2 text-sm text-white/60">{subtitle}</p>
          ) : null}
          <div className="mt-6">{children}</div>
        </Card>
        {footer ? (
          <div className="mt-6 text-center text-sm text-white/50">{footer}</div>
        ) : null}
        <div className="mt-6 flex justify-center">
          <GitHubNavLink />
        </div>
      </div>
    </div>
  );
}
