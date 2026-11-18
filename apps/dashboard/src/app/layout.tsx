import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'
import { StarrySky } from '@/components/starry-sky'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'JAI - Agentic AI System',
  description: 'Private autonomous multi-agent AI execution system',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.className} jai-theme`}>
        <StarrySky />
        {children}
      </body>
    </html>
  )
}
