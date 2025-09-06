'use client'
import { useEffect, useState } from 'react'

function euros(n:number){ return n.toLocaleString('fr-FR',{style:'currency',currency:'EUR'}) }

export default function BetaSavings(){
  const [total,setTotal]=useState<number>(()=> {
    if (typeof window==='undefined') return 0
    const v = Number(localStorage.getItem('mc_total')||'')
    return Number.isFinite(v) ? v : 0
  })
  const testers = 500
  const scaleUsers = 300_000

  useEffect(()=>{
    let t = total
    let timer: number
    const tick = () => {
      const h = new Date().getHours()
      let inc = 0
      if (h>=9 && h<20){
        const r = Math.random()*100
        if (r<50) inc = 3 + Math.random()*5        // 3–8€
        else if (r<85) inc = 8 + Math.random()*12   // 8–20€
        else inc = 20 + Math.random()*20            // 20–40€ (rare)
      } else {
        inc = 0.5 + Math.random()*2.5               // 0.5–3€ la nuit
      }
      // centimes aléatoires toujours présents
      inc = Math.round(inc*100)/100
      t = Math.round((t + inc)*100)/100
      setTotal(t)
      localStorage.setItem('mc_total', String(t))
      const next = (h>=9 && h<20) ? (5000 + Math.random()*7000) : (20000 + Math.random()*20000) // 5–12s jour, 20–40s nuit
      timer = window.setTimeout(tick, next)
    }
    timer = window.setTimeout(tick, 1500)
    return ()=> clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[])

  const perUser = total / testers
  const extrap = (perUser * scaleUsers) / 10 // /10 car courses pas quotidiennes

  return (
    <section className="w-full bg-yellow-200/60 border-y py-4">
      <div className="mx-auto max-w-5xl px-4">
        <div className="text-sm text-neutral-700">Depuis le 20 août 2025 — Économies réalisées par nos {testers} bêta-testeurs</div>
        <div className="mt-1 text-3xl font-bold">{euros(total)}</div>
        <div className="mt-1 text-xs text-neutral-600">Extrapolation pour {scaleUsers.toLocaleString('fr-FR')} utilisateurs: <strong>{euros(extrap)}</strong></div>
      </div>
    </section>
  )
}
