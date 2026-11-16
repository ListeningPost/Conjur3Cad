"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Spinner } from "@/components/ui";

/**
 * Legacy route. Keys are no longer claimed by typing a shared code — you join
 * an org via an invite link and mint your own key on the dashboard. Old emails
 * and bookmarks land here, so forward them.
 */
export default function ClaimPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/dashboard");
  }, [router]);
  return (
    <div className="flex min-h-screen items-center justify-center">
      <Spinner label="Redirecting" />
    </div>
  );
}
