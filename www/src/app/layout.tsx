import type { Metadata } from 'next'
import './globals.css'
import Header from '@/components/Header'
import Footer from '@/components/Footer'

export const metadata: Metadata = {
  title: 'MAXICOURSES',
  description: 'Comparateur temps réel des prix et promos des enseignes proches, optimisé carburant et cartes de fidélité.',
  icons: { icon: '/maxicoursesapp/favicon.ico' }
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <body>
        <Header />
        {children}
        <Footer />
      </body>
    </html>
  )
}
