import Link from 'next/link'

export default function Contact() {
  return (
    <main className="mx-auto max-w-5xl p-8">
      <h1 className="text-3xl font-bold">Contact</h1>
      <p className="mt-4">
        Écrivez-nous : <a className="underline" href="mailto:laurent@maxicourses.fr">laurent@maxicourses.fr</a>
      </p>
      <div className="mt-6 flex gap-4">
        <Link href="/" className="px-3 py-2 border rounded">Accueil</Link>
        <Link href="/features" className="px-3 py-2 border rounded">Fonctionnalités</Link>
      </div>
    </main>
  )
}
