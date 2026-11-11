import type { Metadata } from "next";
import { Toaster } from "sonner";
import { Providers } from "@/components/providers";
import { AuthLayout } from "@/components/AuthLayout";
import "./globals.css";

export const metadata: Metadata = {
  title: "Fly Arrangement - 项目管理与客户管理",
  description: "项目管理 + 客户管理 + AI 助手",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className="antialiased">
        <Providers>
          <AuthLayout>{children}</AuthLayout>
        </Providers>
        <Toaster richColors position="top-center" />
      </body>
    </html>
  );
}
