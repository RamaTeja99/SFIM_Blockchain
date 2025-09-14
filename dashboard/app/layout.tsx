import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'BlockchainVerify - File Integrity Scanner',
  description: 'Analyze files for integrity verification using distributed blockchain consensus and TPM attestation',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className="w-full">
      <body className={`${inter.className} w-full m-0 p-0`}>
        <div className="desktop-container">
          {children}
        </div>
      </body>
    </html>
  )
}