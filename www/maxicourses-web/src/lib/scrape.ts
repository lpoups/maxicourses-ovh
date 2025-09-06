export type ScrapeOk = { ok:true; title:string; price:number; currency:string; url:string; host:string }
export type ScrapeErr = { ok:false; error:string }
export type ScrapeResp = ScrapeOk | ScrapeErr

export async function fetchPrice(url:string): Promise<ScrapeOk>{
  const res = await fetch(`/maxicoursesapp/api/scrape.php?url=${encodeURIComponent(url)}`)
  const data = await res.json() as ScrapeResp
  if (!data.ok) throw new Error(data.error || 'scrape failed')
  return data
}
