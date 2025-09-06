import Link from 'next/link'

export default function Header() {
  return (
    <header className="w-full border-b">
      <nav className="mx-auto max-w-5xl px-4 py-3 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2">
          <img src="/maxicoursesapp/maxicourses-logo.png" alt="MAXICOURSES" className="h-6 w-auto" />
        </Link>
        <div className="flex gap-4 text-sm">
          <Link href="/">Accueil</Link>
          <Link href="/features">Fonctionnalités</Link>
          <a href="https://maxicourses.fr">Investir</a>
          <a href="mailto:laurent@maxicourses.fr">Contact</a>
        </div>
      </nav>
    </header>
  )
}
