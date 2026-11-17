const el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e};
let surveys=[];
const filter=document.querySelector('#category-filter'),list=document.querySelector('#survey-list');
function draw(){
 list.replaceChildren();const shown=surveys.filter(s=>!filter.value||s.event.category===filter.value);
 document.querySelector('#list-status').textContent=shown.length?`${shown.length} 件のアンケート`:'該当するアンケートはありません。';
 for(const s of shown){
  const card=el('section',undefined,'card survey-card'),head=el('div',undefined,'survey-card-head');
  const date=s.event.start?[s.event.start,s.event.end].filter(Boolean).join(' ～ '):'開催日未設定';
  head.append(el('p',date,'eyebrow'),el('span',s.event.category,'category-tag'));card.append(head,el('h2',s.event.title),el('p',s.event.place||''));
  if(s.status==='open'){const a=el('a','このアンケートに回答する','linkbutton');a.href=`/survey?survey=${encodeURIComponent(s.id)}`;card.append(a)}else card.append(el('span','受付終了','badge closed'));
  list.append(card);
 }
}
filter.onchange=draw;
(async()=>{try{const r=await fetch('/api/surveys'),data=await r.json();if(!r.ok)throw Error(data.error);surveys=data.surveys;filter.replaceChildren(new Option('すべてのカテゴリー',''),...data.categories.map(name=>new Option(name,name)));draw()}catch(e){document.querySelector('#list-status').textContent=e.message||'一覧を読み込めませんでした。再読み込みしてください。'}})();
