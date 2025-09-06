'use client'
import { useState } from 'react'
import { fetchPrice } from '@/lib/scrape'

export default function TestScrape(){
  const [url,setUrl] = useState('')
  const [out,setOut] = useState<string>('')

  async function run(){
    setOut('Lecture...')
    try{
      const r = await fetchPrice(url)
      setOut(`OK • ${r.host} • ${r.title} • ${r.price.toFixed(2)} ${r.currency}`)
    }catch(e: unknown){
      const msg = e instanceof Error ? e.message : 'échec'
      setOut('ERREUR • ' + msg)
    }
  }

  return (
    <main className="mx-auto max-w-3xl p-6">
      <h1 className="text-2xl font-bold">Test prix par URL (Carrefour / Monoprix)</h1>
      <p className="text-sm text-neutral-600 mt-2">Colle l’URL d’une page produit du magasin ciblé.</p>
      <div className="mt-4 flex gap-2">
        <input
          value={url}
          onChange={e=>setUrl(e.target.value)}
          placeholder="https://www.carrefour.fr/p/..."
          className="flex-1 border rounded px-3 py-2"
        />
        <button onClick={run} className="px-4 py-2 rounded bg-black text-white">Lire le prix</button>
      </div>
      <pre className="mt-4 p-3 bg-neutral-100 rounded text-sm whitespace-pre-wrap">{out}</pre>
    </main>
  )
}
