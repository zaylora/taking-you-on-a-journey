import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "旅行规划助手",
  description: "Next.js chat frontend for the travel planning backend",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="zh-CN"
      className="h-full antialiased"
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
