// Form definitions are data only; entered text is rendered with textContent.
(()=>{
 const $=s=>document.querySelector(s);
 const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e};
 const types={single:'ラジオボタン（1つ選択）',select:'プルダウン（1つ選択）',multi:'チェックボックス（複数選択）',shorttext:'自由入力（1行）',text:'自由入力（複数行）',number:'数値',date:'日付',scale:'5段階評価',rating:'項目別の5段階評価',count:'項目別の必要数'};
 let questions=[{title:'',type:'single',required:true,options:['','']}];
 let templates=[],loadedTemplate=null,newTemplateId=crypto.randomUUID(),savingTemplate=false;
 const optionTypes=['single','select','multi','rating','count'];
 function report(message){$('#builder-error').textContent=message;$('#builder-error').classList.toggle('hidden',!message)}
 function field(label,control){const l=node('label',label);l.append(control);return l}
 function render(){
  const list=$('#question-builder');list.replaceChildren();$('#question-count').textContent=`${questions.length} / 50 問`;$('#add-question').disabled=questions.length>=50;
  questions.forEach((q,index)=>{
   const card=node('section',undefined,'question-editor'),heading=node('div',undefined,'builder-heading');heading.append(node('h3',`質問 ${index+1}`));
   const controls=node('div',undefined,'builder-actions');
   for(const [label,delta] of [['上へ',-1],['下へ',1]]){const b=node('button',label,'secondary');b.type='button';b.setAttribute('aria-label',`質問 ${index+1} を${label}`);b.disabled=index+delta<0||index+delta>=questions.length;b.onclick=()=>{[questions[index],questions[index+delta]]=[questions[index+delta],questions[index]];render();list.children[index+delta].querySelector('input').focus()};controls.append(b)}
   const remove=node('button','削除','secondary');remove.type='button';remove.setAttribute('aria-label',`質問 ${index+1} を削除`);remove.onclick=()=>{questions.splice(index,1);render()};controls.append(remove);heading.append(controls);card.append(heading);
   const title=node('input');title.required=true;title.maxLength=500;title.placeholder='例：今回の満足度を教えてください';title.value=q.title;title.oninput=()=>{q.title=title.value;report('')};card.append(field('質問文',title));
   const fields=node('div',undefined,'fields'),type=node('select');for(const [value,label] of Object.entries(types))type.append(new Option(label,value));type.value=q.type;type.onchange=()=>{q.type=type.value;delete q.max;if(optionTypes.includes(q.type)&&!q.options)q.options=['',''];render()};fields.append(field('回答形式',type));
   const required=node('select');required.append(new Option('必須','yes'),new Option('任意','no'));required.value=q.required===false?'no':'yes';required.onchange=()=>q.required=required.value==='yes';fields.append(field('回答の必須設定',required));card.append(fields);
   if(optionTypes.includes(q.type)){
    const options=node('textarea');options.rows=4;options.maxLength=10050;options.required=true;options.placeholder='満足\n普通\n不満';options.value=(q.options||[]).join('\n');options.oninput=()=>q.options=options.value.split('\n');card.append(field(['rating','count'].includes(q.type)?'評価する項目（1行に1項目）':'選択肢（1行に1つ）',options));
    card.append(node('p','各項目は200文字以内、最大50件。選択肢の「その他」を選ぶと、補足入力が必須になります。','hint'));
    if(q.type==='multi'){const max=node('input');max.type='number';max.min='1';max.max='50';max.placeholder='空欄なら上限なし';max.value=q.max??'';max.oninput=()=>{if(max.value)q.max=Number(max.value);else delete q.max};card.append(field('最大選択数',max));card.append(node('p','「特になし」は、他の選択肢と同時には選択できません。','hint'))}
   }
   if(q.type==='scale')card.append(node('p','1（低い評価）〜5（高い評価）の選択欄を表示します。','hint'));
   list.append(card);
  });
 }
 $('#add-question').onclick=()=>{if(questions.length>=50)return;questions.push({title:'',type:'text',required:true});render();$('#question-builder').lastElementChild.querySelector('input').focus()};
 function templateStatus(text,error=false){const m=$('#template-message');m.textContent=text;m.classList.toggle('hidden',!text);m.classList.toggle('error',error)}
 function updateTemplateState(){
  $('#template-update').disabled=savingTemplate||!loadedTemplate;$('#template-new').disabled=savingTemplate;$('#apply-template').disabled=savingTemplate;
  $('#template-editing').textContent=loadedTemplate?`編集中のひな形：${loadedTemplate.name}（更新 ${loadedTemplate.revision}）`:'新しいひな形として登録できます。';
 }
 async function requestTemplates(path,body){
  const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),data=await response.json();
  if(!response.ok)throw Error(data.error||'ひな形を保存できませんでした。');return data;
 }
 async function refreshTemplates(selected){
  const data=await requestTemplates('/api/admin/templates');templates=data.templates;
  const select=$('#template-choice'),previous=selected??select.value;select.replaceChildren(new Option('空のフォーム','blank'),...templates.map(t=>new Option(`${t.name}（${t.schema.questions.length}問）`,t.id)));
  select.value=templates.some(t=>t.id===previous)?previous:'blank';
 }
 $('#apply-template').onclick=async()=>{
  if(savingTemplate)return;
  if((questions.some(q=>q.title.trim())||$('#form-intro').value.trim())&&!confirm('現在入力中の質問と説明文を、選択したひな形で置き換えますか？'))return;
  savingTemplate=true;updateTemplateState();
  try{
  await refreshTemplates($('#template-choice').value);
  const selected=templates.find(t=>t.id===$('#template-choice').value);
  if(selected){questions=structuredClone(selected.schema.questions).map(q=>({...q,title:q.title.replace(/^Q\d+\.\s*/, '')}));$('#form-intro').value=selected.schema.intro;loadedTemplate={id:selected.id,name:selected.name,revision:selected.revision};$('#template-name').value=selected.name}
  else{questions=[{title:'',type:'single',required:true,options:['','']}];$('#form-intro').value='';loadedTemplate=null;$('#template-name').value=''}
  newTemplateId=crypto.randomUUID();report('');templateStatus('');updateTemplateState();render();
  }catch(error){templateStatus(error.message,true)}finally{savingTemplate=false;updateTemplateState()}
 };
 async function saveTemplate(updating){
  if(savingTemplate||updating&&!loadedTemplate)return;
  try{
   const name=$('#template-name').value.trim();if(!name||name.length>100)throw Error('ひな形名を100文字以内で入力してください。');
   const definition=window.surveyBuilder.value();savingTemplate=true;updateTemplateState();
   const result=await requestTemplates(updating?'/api/admin/templates/update':'/api/admin/templates',{id:updating?loadedTemplate.id:newTemplateId,name,revision:updating?loadedTemplate.revision:undefined,schema:definition});
   loadedTemplate={id:result.id,name:result.name,revision:result.revision};newTemplateId=crypto.randomUUID();$('#template-name').value=result.name;
   templateStatus(`「${result.name}」を${updating?'更新':'登録'}しました。`);
   try{await refreshTemplates(result.id)}catch{templateStatus('保存しました。一覧の再取得に失敗したため、画面を再読み込みしてください。')}
  }catch(error){templateStatus(error.message,true)}finally{savingTemplate=false;updateTemplateState()}
 }
 $('#template-new').onclick=()=>saveTemplate(false);$('#template-update').onclick=()=>saveTemplate(true);
 window.surveyBuilder={refreshTemplates,value(){
  const fail=message=>{report(message);$('#builder-error').scrollIntoView({block:'center'});throw Error(message)};
  if(!questions.length)fail('質問を1つ以上追加してください。');
  const clean=questions.map((q,i)=>{
   if(!q.title.trim())fail(`質問 ${i+1} の質問文を入力してください。`);
   const value={title:q.title.trim(),type:q.type,required:q.required!==false};
   if(optionTypes.includes(q.type)){
    value.options=(q.options||[]).map(o=>o.trim()).filter(Boolean);
    if(!value.options.length||value.options.length>50||value.options.some(o=>o.length>200))fail(`質問 ${i+1} の選択肢を1〜50件、各200文字以内で入力してください。`);
    if(new Set(value.options).size!==value.options.length)fail(`質問 ${i+1} の選択肢が重複しています。`);
    if(q.type==='multi'&&q.max!==undefined){if(!Number.isInteger(q.max)||q.max<1||q.max>value.options.length)fail(`質問 ${i+1} の最大選択数を選択肢の件数以内で指定してください。`);value.max=q.max}
   }return value;
  });report('');return {intro:$('#form-intro').value,questions:clean};
 }};
 render();
})();
