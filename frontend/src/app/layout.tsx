import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agentic GenBI",
  description: "Mock-first analytical workspace for Agentic GenBI.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
