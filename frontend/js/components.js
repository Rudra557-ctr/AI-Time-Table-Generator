// components.js — reusable UI pieces

export function el(tag, attrs={}, children=[]){
  const n=document.createElement(tag);
  for(const [k,v] of Object.entries(attrs)){
    if(k==='class') n.className=v;
    else if(k==='text') n.textContent=v;
    else if(k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for(const c of [].concat(children)){
    if(c==null) continue;
    if(typeof c==='string') n.appendChild(document.createTextNode(c));
    else n.appendChild(c);
  }
  return n;
}

export function badgeFor(dataset, per){
  if(!per) return el('span',{class:'badge muted', text:'—'});
  if(per.blockers>0) return el('span',{class:'badge err', text:`${per.blockers} blocker`});
  if(per.warnings>0) return el('span',{class:'badge warn', text:`${per.warnings} warn`});
  if(per.rows>0) return el('span',{class:'badge ok', text:`${per.rows} rows`});
  return el('span',{class:'badge muted', text:'empty'});
}

export function issueList(issues){
  const wrap=el('div');
  if(!issues || !issues.length){
    wrap.appendChild(el('div',{class:'notice ok', text:'No issues.'}));
    return wrap;
  }
  for(const it of issues.slice(0,60)){
    const sev = it.severity==='BLOCKER' ? 'err' : 'warn';
    const card=el('div',{class:`issue ${sev}`},[
      el('div',{text: `${it.severity}: ${it.dataset}${it.row?` row ${it.row}`:''}${it.field?` · ${it.field}`:''}`}),
      el('div',{text: it.message}),
      it.fix_hint ? el('div',{class:'meta', text: `Fix: ${it.fix_hint}`}) : null,
    ]);
    wrap.appendChild(card);
  }
  if(issues.length>60) wrap.appendChild(el('div',{class:'meta', text:`... and ${issues.length-60} more`}));
  return wrap;
}

export function toast(msg, kind='ok'){
  const t=el('div',{class:`notice ${kind}`, text: msg, style:'position:fixed;right:12px;bottom:12px;max-width:520px;z-index:99'});
  document.body.appendChild(t);
  setTimeout(()=> t.remove(), 3500);
}

// Table editor: schema-driven rows, emits on change but does NOT auto-save — caller collects rows on Save
export function tableEditor(fields, rows, {onAdd, onDelete}={}){
  const header = fields.map(f=>f.name);
  const wrap=el('div',{class:'table-wrap'});
  const table=el('table');
  const thead=el('thead');
  thead.appendChild(el('tr',{}, header.map(h=> el('th',{text: h})).concat([el('th',{text:''})])));
  const tbody=el('tbody');
  table.appendChild(thead); table.appendChild(tbody); wrap.appendChild(table);

  function enumOptions(field){
    if(field.enum && !field.allow_custom){
      return field.enum.map(v=> `<option value="${v}">${v}</option>`).join('');
    }
    if(field.enum && field.allow_custom){
      return field.enum.map(v=> `<option value="${v}">${v}</option>`).join('');
    }
    return '';
  }

  function rowEl(row, idx){
    const tr=el('tr');
    for(const f of fields){
      const td=el('td');
      const val = row[f.name] ?? '';
      let input;
      if(f.enum){
        input=el('select');
        input.innerHTML=`<option value="">—</option>${enumOptions(f)}`;
        // allow custom value not in enum: inject option
        if(val && ![...input.options].some(o=>o.value===val)){
          const o=document.createElement('option'); o.value=val; o.textContent=val; input.appendChild(o);
        }
        input.value=val;
      } else if(f.dtype==='bool'){
        input=el('select');
        input.innerHTML='<option value="">—</option><option>True</option><option>False</option>';
        // accept true/false variants
        const norm = String(val).toLowerCase();
        if(norm==='true'||norm==='1'||norm==='yes') input.value='True';
        else if(norm==='false'||norm==='0'||norm==='no') input.value='False';
        else input.value=val;
      } else {
        input=el('input',{value: String(val)});
        if(f.dtype==='int64') input.type='number';
        if(f.format==='time') input.placeholder='HH:MM';
        if(f.format==='date') input.placeholder='YYYY-MM-DD';
      }
      // keep row object in sync on input
      input.addEventListener('input', ()=>{ row[f.name]=input.value; });
      input.addEventListener('change', ()=>{ row[f.name]=input.value; });
      td.appendChild(input);
      tr.appendChild(td);
    }
    const tdAct=el('td',{class:'row-actions'});
    const del=el('button',{class:'btn small', text:'✕', onclick:()=>{ tr.remove(); if(onDelete) onDelete(idx, row); }});
    tdAct.appendChild(del);
    tr.appendChild(tdAct);
    return tr;
  }

  function rebuild(){
    tbody.innerHTML='';
    rows.forEach((r,i)=> tbody.appendChild(rowEl(r,i)));
  }
  rebuild();

  function getRows(){
    // read current DOM values (covers edits)
    const out=[];
    [...tbody.children].forEach(tr=>{
      const obj={};
      fields.forEach((f, colIdx)=>{
        const inp=tr.children[colIdx].firstChild;
        obj[f.name]= inp ? inp.value : '';
      });
      out.push(obj);
    });
    // sync back to rows array for caller convenience
    rows.length=0; out.forEach(r=>rows.push(r));
    return out;
  }

  function addRow(prefill={}){
    const r={}; fields.forEach(f=> r[f.name]= prefill[f.name] ?? '');
    rows.push(r);
    tbody.appendChild(rowEl(r, rows.length-1));
  }

  return {wrap, getRows, addRow, rebuild};
}

export function matrixEditor(rowLabels, colLabels, dataSet){
  // dataSet: Set of "row|col" for checked
  const wrap=el('div',{class:'matrix'});
  const table=el('table');
  const thead=el('tr');
  thead.appendChild(el('th',{text:''}));
  colLabels.forEach(c=> thead.appendChild(el('th',{text: c})));
  table.appendChild(thead);
  rowLabels.forEach(r=>{
    const tr=el('tr');
    tr.appendChild(el('th',{text: r}));
    colLabels.forEach(c=>{
      const td=el('td',{class:'mcell'});
      const cb=el('input',{type:'checkbox'});
      cb.checked = dataSet.has(`${r}|${c}`);
      cb.addEventListener('change', ()=>{
        if(cb.checked) dataSet.add(`${r}|${c}`); else dataSet.delete(`${r}|${c}`);
      });
      td.appendChild(cb); tr.appendChild(td);
    });
    table.appendChild(tr);
  });
  wrap.appendChild(table);
  return wrap;
}
