<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01//EN" "http://www.w3.org/TR/html4/strict.dtd">
<html>
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
  <meta http-equiv="Content-Style-Type" content="text/css">
  <title></title>
  <meta name="Generator" content="Cocoa HTML Writer">
  <meta name="CocoaVersion" content="2575.7">
  <style type="text/css">
    p.p1 {margin: 0.0px 0.0px 0.0px 0.0px; font: 12.0px Helvetica}
    p.p2 {margin: 0.0px 0.0px 0.0px 0.0px; font: 12.0px Helvetica; min-height: 14.0px}
  </style>
</head>
<body>
<p class="p1">cat &gt; src/app/compare-live/page.tsx &lt;&lt;'EOF'</p>
<p class="p1">'use client'</p>
<p class="p1">import { useEffect, useMemo, useState } from 'react'</p>
<p class="p1">import { fetchPrice } from '@/lib/scrape'</p>
<p class="p2"><br></p>
<p class="p1">type Row = {</p>
<p class="p1"><span class="Apple-converted-space">  </span>id: string</p>
<p class="p1"><span class="Apple-converted-space">  </span>name: string</p>
<p class="p1"><span class="Apple-converted-space">  </span>qty: number</p>
<p class="p1"><span class="Apple-converted-space">  </span>urlA: string</p>
<p class="p1"><span class="Apple-converted-space">  </span>urlB: string</p>
<p class="p1"><span class="Apple-converted-space">  </span>priceA?: number</p>
<p class="p1"><span class="Apple-converted-space">  </span>priceB?: number</p>
<p class="p1">}</p>
<p class="p1">const KEY = 'mc_items_v1'</p>
<p class="p1">function euros(n:number){ return n.toLocaleString('fr-FR',{style:'currency',currency:'EUR'}) }</p>
<p class="p2"><br></p>
<p class="p1">export default function CompareLive(){</p>
<p class="p1"><span class="Apple-converted-space">  </span>const [rows,setRows] = useState&lt;Row[]&gt;(()=&gt; {</p>
<p class="p1"><span class="Apple-converted-space">    </span>if (typeof window==='undefined') return []</p>
<p class="p1"><span class="Apple-converted-space">    </span>try { return JSON.parse(localStorage.getItem(KEY)||'[]') } catch { return [] }</p>
<p class="p1"><span class="Apple-converted-space">  </span>})</p>
<p class="p1"><span class="Apple-converted-space">  </span>useEffect(()=&gt;{ if (typeof window!=='undefined') localStorage.setItem(KEY, JSON.stringify(rows)) },[rows])</p>
<p class="p2"><br></p>
<p class="p1"><span class="Apple-converted-space">  </span>const totalA = useMemo(()=&gt;rows.reduce((s,r)=&gt;s + (r.priceA||0)*(r.qty||0),0),[rows])</p>
<p class="p1"><span class="Apple-converted-space">  </span>const totalB = useMemo(()=&gt;rows.reduce((s,r)=&gt;s + (r.priceB||0)*(r.qty||0),0),[rows])</p>
<p class="p1"><span class="Apple-converted-space">  </span>const cheaper = totalA===totalB ? 'Égalité' : (totalA&lt;totalB ? 'Carrefour Market — Fondaudège' : 'Monoprix — Le Bouscat')</p>
<p class="p2"><br></p>
<p class="p1"><span class="Apple-converted-space">  </span>function addRow(){</p>
<p class="p1"><span class="Apple-converted-space">    </span>const i = rows.length + 1</p>
<p class="p1"><span class="Apple-converted-space">    </span>setRows([...rows, { id:String(Date.now()), name:`Produit ${i}`, qty:1, urlA:'', urlB:'' }])</p>
<p class="p1"><span class="Apple-converted-space">  </span>}</p>
<p class="p1"><span class="Apple-converted-space">  </span>function set&lt;K extends keyof Row&gt;(id:string, key:K, val:Row[K]){</p>
<p class="p1"><span class="Apple-converted-space">    </span>setRows(rows.map(r=&gt; r.id===id ? {...r, [key]:val} : r))</p>
<p class="p1"><span class="Apple-converted-space">  </span>}</p>
<p class="p1"><span class="Apple-converted-space">  </span>function remove(id:string){ setRows(rows.filter(r=&gt;r.id!==id)) }</p>
<p class="p2"><br></p>
<p class="p1"><span class="Apple-converted-space">  </span>async function readA(r:Row){</p>
<p class="p1"><span class="Apple-converted-space">    </span>if (!r.urlA) return</p>
<p class="p1"><span class="Apple-converted-space">    </span>const d = await fetchPrice(r.urlA)</p>
<p class="p1"><span class="Apple-converted-space">    </span>setRows(rows.map(x=&gt; x.id===r.id ? {...x, name: x.name.startsWith('Produit ')? d.title : x.name, priceA:d.price} : x))</p>
<p class="p1"><span class="Apple-converted-space">  </span>}</p>
<p class="p1"><span class="Apple-converted-space">  </span>async function readB(r:Row){</p>
<p class="p1"><span class="Apple-converted-space">    </span>if (!r.urlB) return</p>
<p class="p1"><span class="Apple-converted-space">    </span>const d = await fetchPrice(r.urlB)</p>
<p class="p1"><span class="Apple-converted-space">    </span>setRows(rows.map(x=&gt; x.id===r.id ? {...x, name: x.name.startsWith('Produit ')? d.title : x.name, priceB:d.price} : x))</p>
<p class="p1"><span class="Apple-converted-space">  </span>}</p>
<p class="p2"><br></p>
<p class="p1"><span class="Apple-converted-space">  </span>return (</p>
<p class="p1"><span class="Apple-converted-space">    </span>&lt;main className="mx-auto max-w-5xl p-6"&gt;</p>
<p class="p1"><span class="Apple-converted-space">      </span>&lt;h1 className="text-2xl font-bold"&gt;Comparaison live Carrefour vs Monoprix&lt;/h1&gt;</p>
<p class="p1"><span class="Apple-converted-space">      </span>&lt;p className="text-sm text-neutral-600 mt-1"&gt;</p>
<p class="p1"><span class="Apple-converted-space">        </span>Colle les URLs produit Carrefour (Fondaudège) et Monoprix (Le Bouscat). Clique “Lire prix”.</p>
<p class="p1"><span class="Apple-converted-space">      </span>&lt;/p&gt;</p>
<p class="p2"><br></p>
<p class="p1"><span class="Apple-converted-space">      </span>&lt;div className="mt-4"&gt;</p>
<p class="p1"><span class="Apple-converted-space">        </span>&lt;button onClick={addRow} className="px-4 py-2 bg-black text-white rounded text-sm"&gt;Ajouter un produit&lt;/button&gt;</p>
<p class="p1"><span class="Apple-converted-space">      </span>&lt;/div&gt;</p>
<p class="p2"><br></p>
<p class="p1"><span class="Apple-converted-space">      </span>&lt;table className="w-full text-sm mt-4"&gt;</p>
<p class="p1"><span class="Apple-converted-space">        </span>&lt;thead&gt;</p>
<p class="p1"><span class="Apple-converted-space">          </span>&lt;tr&gt;</p>
<p class="p1"><span class="Apple-converted-space">            </span>&lt;th className="text-left"&gt;Produit&lt;/th&gt;</p>
<p class="p1"><span class="Apple-converted-space">            </span>&lt;th&gt;Qté&lt;/th&gt;</p>
<p class="p1"><span class="Apple-converted-space">            </span>&lt;th className="text-left"&gt;URL Carrefour&lt;/th&gt;</p>
<p class="p1"><span class="Apple-converted-space">            </span>&lt;th className="text-left"&gt;URL Monoprix&lt;/th&gt;</p>
<p class="p1"><span class="Apple-converted-space">            </span>&lt;th&gt;€/Carrefour&lt;/th&gt;</p>
<p class="p1"><span class="Apple-converted-space">            </span>&lt;th&gt;€/Monoprix&lt;/th&gt;</p>
<p class="p1"><span class="Apple-converted-space">            </span>&lt;th&gt;&lt;/th&gt;</p>
<p class="p1"><span class="Apple-converted-space">          </span>&lt;/tr&gt;</p>
<p class="p1"><span class="Apple-converted-space">        </span>&lt;/thead&gt;</p>
<p class="p1"><span class="Apple-converted-space">        </span>&lt;tbody&gt;</p>
<p class="p1"><span class="Apple-converted-space">          </span>{rows.map(r=&gt;(</p>
<p class="p1"><span class="Apple-converted-space">            </span>&lt;tr key={r.id} className="border-t align-top"&gt;</p>
<p class="p1"><span class="Apple-converted-space">              </span>&lt;td className="py-2"&gt;</p>
<p class="p1"><span class="Apple-converted-space">                </span>&lt;input value={r.name} onChange={e=&gt;set(r.id,'name',e.target.value)} className="border rounded px-2 py-1 w-48"/&gt;</p>
<p class="p1"><span class="Apple-converted-space">              </span>&lt;/td&gt;</p>
<p class="p1"><span class="Apple-converted-space">              </span>&lt;td className="py-2 text-center"&gt;</p>
<p class="p1"><span class="Apple-converted-space">                </span>&lt;input type="number" min={0} value={r.qty} onChange={e=&gt;set(r.id,'qty', Number(e.target.value)||0)} className="border rounded px-2 py-1 w-20 text-right"/&gt;</p>
<p class="p1"><span class="Apple-converted-space">              </span>&lt;/td&gt;</p>
<p class="p1"><span class="Apple-converted-space">              </span>&lt;td className="py-2"&gt;</p>
<p class="p1"><span class="Apple-converted-space">                </span>&lt;div className="flex gap-2"&gt;</p>
<p class="p1"><span class="Apple-converted-space">                  </span>&lt;input value={r.urlA} onChange={e=&gt;set(r.id,'urlA',e.target.value)} placeholder="https://www.carrefour.fr/p/..." className="border rounded px-2 py-1 w-full"/&gt;</p>
<p class="p1"><span class="Apple-converted-space">                  </span>&lt;button onClick={()=&gt;readA(r)} className="px-2 py-1 border rounded"&gt;Lire prix&lt;/button&gt;</p>
<p class="p1"><span class="Apple-converted-space">                </span>&lt;/div&gt;</p>
<p class="p1"><span class="Apple-converted-space">              </span>&lt;/td&gt;</p>
<p class="p1"><span class="Apple-converted-space">              </span>&lt;td className="py-2"&gt;</p>
<p class="p1"><span class="Apple-converted-space">                </span>&lt;div className="flex gap-2"&gt;</p>
<p class="p1"><span class="Apple-converted-space">                  </span>&lt;input value={r.urlB} onChange={e=&gt;set(r.id,'urlB',e.target.value)} placeholder="https://courses.monoprix.fr/products/..." className="border rounded px-2 py-1 w-full"/&gt;</p>
<p class="p1"><span class="Apple-converted-space">                  </span>&lt;button onClick={()=&gt;readB(r)} className="px-2 py-1 border rounded"&gt;Lire prix&lt;/button&gt;</p>
<p class="p1"><span class="Apple-converted-space">                </span>&lt;/div&gt;</p>
<p class="p1"><span class="Apple-converted-space">              </span>&lt;/td&gt;</p>
<p class="p1"><span class="Apple-converted-space">              </span>&lt;td className="py-2 text-center"&gt;{r.priceA?.toFixed(2) ?? '-'}&lt;/td&gt;</p>
<p class="p1"><span class="Apple-converted-space">              </span>&lt;td className="py-2 text-center"&gt;{r.priceB?.toFixed(2) ?? '-'}&lt;/td&gt;</p>
<p class="p1"><span class="Apple-converted-space">              </span>&lt;td className="py-2 text-center"&gt;</p>
<p class="p1"><span class="Apple-converted-space">                </span>&lt;button onClick={()=&gt;remove(r.id)} className="px-2 py-1 border rounded"&gt;Suppr&lt;/button&gt;</p>
<p class="p1"><span class="Apple-converted-space">              </span>&lt;/td&gt;</p>
<p class="p1"><span class="Apple-converted-space">            </span>&lt;/tr&gt;</p>
<p class="p1"><span class="Apple-converted-space">          </span>))}</p>
<p class="p1"><span class="Apple-converted-space">          </span>{rows.length===0 &amp;&amp; &lt;tr&gt;&lt;td colSpan={7} className="py-6 text-neutral-500"&gt;Aucun produit. Cliquez “Ajouter un produit”.&lt;/td&gt;&lt;/tr&gt;}</p>
<p class="p1"><span class="Apple-converted-space">        </span>&lt;/tbody&gt;</p>
<p class="p1"><span class="Apple-converted-space">        </span>&lt;tfoot&gt;</p>
<p class="p1"><span class="Apple-converted-space">          </span>&lt;tr className="border-t font-semibold"&gt;</p>
<p class="p1"><span class="Apple-converted-space">            </span>&lt;td&gt;Total&lt;/td&gt;&lt;td&gt;&lt;/td&gt;&lt;td&gt;&lt;/td&gt;&lt;td&gt;&lt;/td&gt;</p>
<p class="p1"><span class="Apple-converted-space">            </span>&lt;td className="text-center"&gt;{euros(totalA)}&lt;/td&gt;</p>
<p class="p1"><span class="Apple-converted-space">            </span>&lt;td className="text-center"&gt;{euros(totalB)}&lt;/td&gt;</p>
<p class="p1"><span class="Apple-converted-space">            </span>&lt;td className="text-center"&gt;{cheaper}&lt;/td&gt;</p>
<p class="p1"><span class="Apple-converted-space">          </span>&lt;/tr&gt;</p>
<p class="p1"><span class="Apple-converted-space">        </span>&lt;/tfoot&gt;</p>
<p class="p1"><span class="Apple-converted-space">      </span>&lt;/table&gt;</p>
<p class="p1"><span class="Apple-converted-space">    </span>&lt;/main&gt;</p>
<p class="p1"><span class="Apple-converted-space">  </span>)</p>
<p class="p1">}</p>
<p class="p1">EOF</p>
</body>
</html>
