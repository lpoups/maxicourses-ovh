'use client';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center h-screen bg-bg text-text gap-4">
      <h2 className="text-xl font-bold text-accent-red">Erreur Dashboard</h2>
      <p className="text-sm text-text-muted max-w-md text-center">
        {error.message || 'Une erreur est survenue.'}
      </p>
      <button
        onClick={reset}
        className="px-4 py-2 rounded-lg bg-accent-blue/20 text-accent-blue border border-accent-blue/30 hover:bg-accent-blue/30 transition-colors"
      >
        Recharger
      </button>
    </div>
  );
}
