import type { Metadata } from 'next';
import localFont from 'next/font/local';
import './globals.css';
// Next ships Geist locally; no font download is needed during build or use.
const geist = localFont({ src: '../node_modules/next/dist/next-devtools/server/font/geist-latin.woff2', variable: '--font-app', display: 'swap', fallback: ['Microsoft YaHei', 'Segoe UI', 'sans-serif'] });
export const metadata: Metadata = { title: 'BiliLM · 视频学习笔记', description: '在本地，把视频变成可以探索的知识。' };
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body className={geist.variable}>{children}</body></html>;
}
