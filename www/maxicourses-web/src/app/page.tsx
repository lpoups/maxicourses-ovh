import BetaSavings from '@/components/BetaSavings'

export default function Home() {
  return (
    <main className="min-h-screen flex flex-col">
      <BetaSavings />
      <div className="flex-1 flex flex-col items-center justify-center p-8">
        <h1 className="text-4xl font-bold tracking-tight">MAXICOURSES</h1>
        <p className="mt-4 max-w-xl text-center">
          Comparateur temps réel des prix et promos des enseignes proches, optimisé carburant et cartes de fidélité.
        </p>
        <div className="mt-6 flex gap-3">
          <a href="https://maxicourses.fr" className="px-4 py-2 rounded bg-black text-white">Contact / Investir</a>
          <a href="/maxicoursesapp/" className="px-4 py-2 rounded border">Rafraîchir</a>
        </div>
      </div>
    </main>
  );
}
