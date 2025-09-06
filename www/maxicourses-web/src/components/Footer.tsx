export default function Footer() {
  return (
    <footer className="w-full border-t mt-12">
      <div className="mx-auto max-w-5xl px-4 py-6 text-sm flex items-center justify-between">
        <p>© {new Date().getFullYear()} MAXICOURSES</p>
        <div className="flex gap-4">
          <a href="mailto:laurent@maxicourses.fr">Contact</a>
          <a href="https://maxicourses.fr">Investir</a>
        </div>
      </div>
    </footer>
  )
}
