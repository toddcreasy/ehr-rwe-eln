import type { Metadata } from "next";
import { Geist, Geist_Mono, Source_Serif_4 } from "next/font/google";
import "./globals.css";
import Disclaimer from "./disclaimer";
import Shell from "./shell";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

const serif = Source_Serif_4({
  variable: "--font-serif-display",
  subsets: ["latin"],
  weight: ["600"],
});

export const metadata: Metadata = {
  title: "RWE Workbench",
  description: "Real world evidence from one synthetic patient population",
};

// Runs before first paint: the saved choice, else the system setting. Help on the page is on
// unless the visitor turned it off, and its buttons pulse until the first note is opened.
const THEME = `try{var t=localStorage.getItem("theme");if(t==="dark"||(!t&&matchMedia("(prefers-color-scheme: dark)").matches))document.documentElement.classList.add("dark");if(localStorage.getItem("docs")==="off")document.documentElement.classList.add("docs-off");if(!localStorage.getItem("help-seen"))document.documentElement.classList.add("help-new")}catch(e){}`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} ${serif.variable} h-full antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME }} />
      </head>
      <body className="min-h-full flex flex-col">
        <Shell>{children}</Shell>
        <Disclaimer />
      </body>
    </html>
  );
}
