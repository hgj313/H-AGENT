import type { Metadata } from "next";
import { TopNav } from "@/components/layout/TopNav";
import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "H-Agent",
  description: "通用 Agent 平台 - 设计审查 + 通用对话",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-brand-50/30 text-gray-900 antialiased">
        <Providers>
          <TopNav />
          <main className="mx-auto max-w-7xl px-6 py-6">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
