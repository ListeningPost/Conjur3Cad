import type { Metadata } from "next";
import {
  Inter_Tight,
  Saira_Stencil_One,
  Share_Tech_Mono,
  JetBrains_Mono,
} from "next/font/google";
import { AuthContextProvider } from "@/context/AuthContext";
import "./globals.css";

// Conjur3 type system, exposed as CSS variables consumed by globals.css @theme.
const interTight = Inter_Tight({
  subsets: ["latin"],
  variable: "--font-inter-tight",
  display: "swap",
});
const saira = Saira_Stencil_One({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-saira",
  display: "swap",
});
const shareTech = Share_Tech_Mono({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-share-tech",
  display: "swap",
});
const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Conjur3 · Autonomous parametric CAD for manufacturing",
  description:
    "Conjur3 is an autonomous design agent that operates a parametric CAD kernel directly — producing real, machinable engineering output. Manage your team's access here.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${interTight.variable} ${saira.variable} ${shareTech.variable} ${jetbrains.variable}`}
    >
      <body>
        <AuthContextProvider>{children}</AuthContextProvider>
      </body>
    </html>
  );
}
