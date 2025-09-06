<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Maxicourses — Comparateur multi-enseignes</title>
<style>
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:24px}
  h1{font-size:22px;margin:0}
  .muted{color:#666;font-size:13px;margin-top:4px}
  textarea,input,button{font:inherit}
  .row{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}
  table{width:100%;border-collapse:collapse;margin-top:16px;font-size:14px}
  th,td{padding:8px;border-top:1px solid #eee;vertical-align:top}
  th{text-align:left}
  .btn{border:1px solid #000;background:#000;color:#fff;border-radius:6px;padding:6px 10px;font-size:13px;cursor:pointer}
  .btn-ghost{border:1px solid #ccc;background:#fff;color:#000;border-radius:6px;padding:6px 10px;font-size:13px;cursor:pointer}
  .mono{font-family:ui-monospace,Menlo,Consolas,monospace}
  .center{text-align:center}
  .green{background:#ecfdf5;font-weight:600}
  .price{width:100px;text-align:right}
  .url{width:100%}
</style>
</head>
<body>
  <h1>Comparateur multi-enseignes</h1>
  <div class="muted">Colle des URL produits (Monoprix, Leclerc, Carrefour…). Clique “Lire prix”. Si bloqué, saisis le prix manuellement.</div>

  <div class="row">
    <div>
      <label class="muted">Coller la liste (une ligne par produit, “2x …” possible)</label>
      <textarea id="importText" rows="6" class="mono" style="width:100%;margin-top:6px;">2x Coca-Cola 1,75L
Pâtes 500g
3 Lait demi-écrémé 1L</textarea>
      <div style="margin-top:8px;display:flex;gap:8px">
        <button id="btnImport" class="btn">Importer (remplace)</button>
        <button id="btnAdd" class="btn-ghost">+ Ligne</button>
        <button id="btnClear" class="btn-ghost">Vider</button>
      </div>
    </div>
    <div class="muted">
      Domains pris en charge par l’API: monoprix.fr, carrefour.fr, intermarche.com, leclercdrive.fr, e.leclerc, auchan.fr, coursesu.com, systeme-u.fr, coradrive.fr, chronodrive.com.
    </div>
  </div>

  <table id="tbl">
    <thead>
      <tr>
        <th>Produit</th>
        <th class="center">Qté</th>
        <th>URL A</th>
        <th>URL B</th>
        <th>URL C</th>
        <th class="center">€/A</th>
        <th class="center">€/B</th>
        <th class="center">€/C</th>
        <th class="center">Moins cher</th>
        <th class="center"></th>
      </tr>
    </thead>
    <tbody></tbody>
    <tfoot>
      <tr>
        <td>Total</td><td></td><td></td><td></td><td></td>
        <td class="center" id="totA">0,00 €</td>
        <td class="center" id="totB">0,00 €</td>
        <td class="center" id="totC">0,00 €</td>
        <td class="center" id="winner">—</td>
        <td></td>
      </tr>
    </tfoot>
  </table>

<script>
const API = '/maxicoursesapp/api/scrape2.php';
const KEY = 'mc_items_v2';
const fmtEUR = n => (n||0).toLocaleString('fr-FR',{style:'currency',currency:'EUR'});

let rows = load(); render();

document.getElementById('btnImport').onclick = () => {
  const txt = document.getElementById('importText').value;
  rows = parseLines(txt);
  save(); render();
};
document.getElementById('btnAdd').onclick = () => { addRow(); save(); render(); };
document.getElementById('btnClear').onclick = () => { rows = []; save(); render(); };

function load(){ try { return JSON.parse(localStorage.getItem(KEY)||'[]'); } catch { return []; } }
function save(){ localStorage.setItem(KEY, JSON.stringify(rows)); }

function parseLines(txt){
  const now = Date.now();
  return txt.split(/\r?\n/).map(s=>s.trim()).filter(Boolean).slice(0,100).map((l,i)=>{
    let qty = 1, name = l;
    const m = l.match(/^\s*(\d+(?:[.,]\d+)?)\s*(?:x|×)?\s*(.+)$/i);
    if (m){ qty = parseFloat(m[1].replace(',','.')); name = m[2].trim(); }
    if (!Number.isFinite(qty) || qty<=0) qty = 1;
    return { id:String(now+i), name, qty, urlA:'', urlB:'', urlC:'', priceA:null, priceB:null, priceC:null };
  });
}

function addRow(){ rows.push({id:String(Date.now()), name:'Produit '+(rows.length+1), qty:1, urlA:'', urlB:'', urlC:'', priceA:null, priceB:null, priceC:null}); }
function setField(id, key, val){ rows = rows.map(r => r.id===id ? {...r, [key]:val} : r); }

async function readPrice(id, col){
  const r = rows.find(x=>x.id===id); if(!r) return;
  const url = r['url'+col]; if(!url) return;
  try{
    const res = await fetch(`${API}?url=${encodeURIComponent(url)}`);
    const data = await res.json();
    if(!data.ok) throw new Error(data.error||'échec');
    if (r.name.startsWith('Produit ')) r.name = data.title || r.name;
    r['price'+col] = Number(data.price);
  }catch(e){ alert(`Erreur lecture prix (${col}) : ${e.message||e}`); }
  save(); render();
}

function cheaperTag(r){
  const p = [['A',r.priceA],['B',r.priceB],['C',r.priceC]].filter(x=>x[1]!=null);
  if (p.length<2) return '—';
  p.sort((x,y)=>x[1]-y[1]);
  const best = p[0], second = p[1];
  const diff = (second[1]-best[1])*(r.qty||0);
  return diff>0 ? `${best[0]} (+${fmtEUR(diff)})` : best[0];
}

function render(){
  const tbody = document.querySelector('#tbl tbody');
  tbody.innerHTML = '';
  let totA=0, totB=0, totC=0;

  for(const r of rows){
    const tr = document.createElement('tr');

    const tdName = document.createElement('td');
    const inpName = Object.assign(document.createElement('input'), {value:r.name});
    inpName.oninput = e => { setField(r.id,'name', e.target.value); save(); };
    tdName.appendChild(inpName); tr.appendChild(tdName);

    const tdQty = document.createElement('td'); tdQty.className='center';
    const inpQty = Object.assign(document.createElement('input'), {type:'number', value:r.qty, min:'0', style:'width:80px;text-align:right'});
    inpQty.oninput = e => { setField(r.id,'qty', parseFloat(e.target.value)||0); save(); render(); };
    tdQty.appendChild(inpQty); tr.appendChild(tdQty);

    ['A','B','C'].forEach(col=>{
      const td = document.createElement('td');
      const input = Object.assign(document.createElement('input'), {value:r['url'+col], placeholder:`URL produit ${col}`, className:'url'});
      input.oninput = e => { setField(r.id, 'url'+col, e.target.value); save(); };
      const btn = Object.assign(document.createElement('button'), {innerText:'Lire prix', className:'btn-ghost'});
      btn.onclick = ()=> readPrice(r.id, col);
      td.append(input, btn); tr.appendChild(td);
    });

    ['A','B','C'].forEach(col=>{
      const td = document.createElement('td'); td.className='center';
      const show = document.createElement('div'); show.innerText = r['price'+col]!=null ? Number(r['price'+col]).toFixed(2) : '-';
      const edit = Object.assign(document.createElement('input'), {placeholder:'saisir €', className:'price'});
      edit.onblur = e => { const n = parseFloat(String(e.target.value).replace(',','.')); if(Number.isFinite(n)) { setField(r.id,'price'+col, n); save(); render(); } };
      td.append(show, edit); tr.appendChild(td);
    });

    const tdBest = document.createElement('td'); tdBest.className='center';
    tdBest.innerText = cheaperTag(r);
    tr.appendChild(tdBest);

    const tdDel = document.createElement('td'); tdDel.className='center';
    const bDel = Object.assign(document.createElement('button'), {innerText:'Suppr', className:'btn-ghost'});
    bDel.onclick = ()=> { rows = rows.filter(x=>x.id!==r.id); save(); render(); };
    tdDel.appendChild(bDel); tr.appendChild(tdDel);

    totA += (r.priceA||0) * (r.qty||0);
    totB += (r.priceB||0) * (r.qty||0);
    totC += (r.priceC||0) * (r.qty||0);

    tbody.appendChild(tr);
  }

  document.getElementById('totA').innerText = fmtEUR(totA);
  document.getElementById('totB').innerText = fmtEUR(totB);
  document.getElementById('totC').innerText = fmtEUR(totC);
  const totals = [['A',totA],['B',totB],['C',totC]].filter(x=>x[1]>0).sort((x,y)=>x[1]-y[1]);
  document.getElementById('winner').innerText = totals.length>1 ? `${totals[0][0]} (écart ${fmtEUR(totals[1][1]-totals[0][1])})` : (totals[0]?totals[0][0]:'—');
}
</script>
</body>
</html>
