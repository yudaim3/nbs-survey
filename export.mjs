import fs from 'node:fs/promises';
import path from 'node:path';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

let input=''; for await (const chunk of process.stdin) input+=chunk;
const data=JSON.parse(input),target=process.argv[2];
const {schema,responses,event,summary}=data;
const wb=Workbook.create(),specs=[];
const excelJst=iso=>Date.parse(iso)/86400000+25569+9/24;
const safe=v=>typeof v==='string'&&/^[=+@-]/.test(v)?"'"+v:v;
const chunks=(text,size=300)=>{const out=[];let part='',length=0,lines=0;for(const ch of Array.from(String(text??''))){part+=ch;length++;if(ch==='\n')lines++;if(length>=size||lines>=12){out.push(part);part='';length=0;lines=0}}if(part)out.push(part);return out.length?out:[''];};
function sheet(name,title,headers,rows,widths){
 const s=wb.worksheets.add(name),cols=headers.length,last=rows.length+4;
 s.showGridLines=false;s.getRangeByIndexes(0,0,Math.max(last,5),cols).format.font={name:'Yu Gothic',size:10,color:'#243E3A'};
 s.getRange('A2').values=[[title]];s.getRange('A2').format.font={name:'Yu Gothic',size:15,bold:true,color:'#173F38'};
 s.getRangeByIndexes(3,0,1,cols).values=[headers];s.getRangeByIndexes(3,0,1,cols).format={fill:'#285E53',font:{name:'Yu Gothic',bold:true,color:'#FFFFFF'},rowHeight:32,wrapText:true,verticalAlignment:'center'};
 if(rows.length)s.getRangeByIndexes(4,0,rows.length,cols).values=rows.map(row=>row.map(safe));
 const body=s.getRangeByIndexes(4,0,Math.max(1,rows.length),cols);body.format.rowHeight=26;body.format.verticalAlignment='top';body.format.wrapText=true;
 widths.forEach((w,i)=>s.getRangeByIndexes(0,i,Math.max(5,last),1).format.columnWidth=w);
 for(let i=0;i<rows.length;i++){if(i%2===1)s.getRangeByIndexes(i+4,0,1,cols).format.fill='#F0F5F0';let lines=1;rows[i].forEach((v,j)=>{if(typeof v==='string')lines=Math.max(lines,v.split('\n').reduce((sum,line)=>sum+Math.max(1,Math.ceil(Array.from(line).length/Math.max(7,widths[j]/2.1))),0))});s.getRangeByIndexes(i+4,0,1,cols).format.rowHeight=Math.min(405,Math.max(26,lines*16+8));}
 s.freezePanes.freezeRows(4);specs.push({name,rows:rows.length+4,cols});return s;
}
const basics=[['開催名',event.title,''],['実施期間',[event.start,event.end].filter(Boolean).join(' ～ '),''],['実施場所',event.place,''],['回答件数',summary.total,'回答者名の入力有無によらず受付件数を集計'],['全体満足度（平均）',summary.questions.q1.average,`5点満点・有効回答 ${summary.questions.q1.answered} 件`],['仕事のしやすさ（平均）',summary.questions.q2.average,`5点満点・有効回答 ${summary.questions.q2.answered} 件`],['コミュニケーション改善の割合',summary.communication_rate,`Q5の肯定的2区分 / 有効回答 ${summary.questions.q5.answered} 件`],['出力日時',data.exported_at,'日本時間'],['集計方法','出力時点の確定値','空欄は未回答。割合の分母は各設問の有効回答数。'],['回答の取扱い','1送信を1件として集計','ログインなしのため、同一人物の別送信は自動で判別しません。']];
basics.push(['','',''],['設問・選択肢','人数','有効回答に対する割合']);
for(const q of schema.questions.filter(q=>q.type==='single')){const s=summary.questions[q.id];basics.push([q.title,null,null]);for(const [option,n] of Object.entries(s.counts))basics.push([option,n,s.answered?n/s.answered:null]);basics.push(['未回答',s.missing,null]);}
basics.push(['','',''],['Q12 必要な水回り','人数','集計区分']);
for(const row of summary.questions.q12.rows){for(const [v,n] of Object.entries(row.counts))basics.push([row.label,n,v]);basics.push([row.label,row.missing,'未回答']);}
const main=sheet('集計サマリー',`${event.title} アンケート集計`,['項目','結果','補足'],basics,[56,58,65]);
main.getRange('B12').values=[[excelJst(data.exported_at)]];main.getRange('B12').setNumberFormat('yyyy-mm-dd hh:mm:ss');
main.getRange('B9:B10').setNumberFormat('0.00');main.getRange('B11').setNumberFormat('0.0%');
basics.forEach((row,i)=>{if(typeof row[2]==='number')main.getRangeByIndexes(i+4,2,1,1).setNumberFormat('0.0%')});
const equipment=summary.questions.q7.rows.map(r=>[r.label,r.answered,r.average,r.low,r.missing]);
const eq=sheet('設備評価','Q7 設備・環境の評価',['設備・環境','有効回答数','平均（5点満点）','低評価（1〜2）','未回答'],equipment,[35,18,22,22,18]);eq.getRange('C5:C15').setNumberFormat('0.00');
const multis=[];for(const q of schema.questions.filter(q=>q.type==='multi')){const s=summary.questions[q.id];for(const [o,n] of Object.entries(s.counts).sort((a,b)=>b[1]-a[1]))multis.push([`Q${q.number}`,q.title,o,n,s.answered?n/s.answered:null,s.answered]);}
const mu=sheet('複数選択集計','複数選択の集計（割合の合計は100%を超える場合があります）',['設問','質問内容','選択肢','選択件数','選択割合','有効回答数'],multis,[10,55,48,15,15,18]);if(multis.length)mu.getRangeByIndexes(4,4,multis.length,1).setNumberFormat('0.0%');
const textRows=[];for(const r of responses){for(const q of schema.questions){const value=q.type==='text'?r.answers[q.id]:r.other[q.id];if(!value)continue;chunks(value).forEach((part,i,parts)=>textRows.push([r.id,r.name||'',`Q${q.number}${q.type==='text'?'':' その他'}`,q.title,i+1,parts.length,part]));}}
sheet('自由記述一覧','自由記述の原文（長文は同じ受付ID・設問の連番で続きます）',['受付ID','回答者名（任意）','設問','質問内容','連番','分割数','回答原文'],textRows,[40,22,16,52,10,10,100]);
const raw=[];for(const r of responses){for(const q of schema.questions.filter(q=>q.type!=='text')){const a=r.answers[q.id];if(q.type==='single')raw.push([r.id,r.created_at,r.name,`Q${q.number}`,q.title,a??null]);else if(q.type==='multi')for(const o of q.options)raw.push([r.id,r.created_at,r.name,`Q${q.number}`,o,a===undefined?null:Number(a.includes(o))]);else for(const o of q.options)raw.push([r.id,r.created_at,r.name,`Q${q.number}`,o,a?.[o]===undefined?null:a[o]==='6以上'?'6以上':Number(a[o])]);}}
raw.forEach(row=>row[1]=excelJst(row[1]));
const rawSheet=sheet('回答データ','回答データ（複数選択は選択1・未選択0、未回答は空欄）',['受付ID','受付日時（日本時間）','回答者名（任意）','設問','項目','回答'],raw,[40,30,22,10,58,50]);
if(raw.length)rawSheet.getRangeByIndexes(4,1,raw.length,1).setNumberFormat('yyyy-mm-dd hh:mm:ss');
const questionRows=[];for(const q of schema.questions)questionRows.push([`Q${q.number}`,schema.sections[q.section-1],q.title,{text:'自由記述',single:'単一選択',multi:'複数選択',rating:'5段階評価',count:'必要数'}[q.type],q.options?.join('\n')||'',q.max?'最大3つ':q.id==='q8'?'「特になし」は他の項目と同時選択不可':q.id==='q12'?'1・2・3・4・5・6以上。6以上を6として平均計算しない。':'']);
sheet('設問一覧','アンケートの設問と選択肢',['設問','セクション','質問内容','回答形式','項目・選択肢','条件'],questionRows,[10,42,64,18,58,48]);
wb.recalculate();
if(process.env.AWAJI_QA_DIR){
 const dir=process.env.AWAJI_QA_DIR;await fs.mkdir(dir,{recursive:true});
 for(const spec of specs.filter(s=>!process.env.AWAJI_QA_SHEETS||process.env.AWAJI_QA_SHEETS.split(',').includes(s.name))){const pic=await wb.render({sheetName:spec.name,range:`A1:${String.fromCharCode(64+Math.min(spec.cols,7))}${Math.min(spec.rows,17)}`,scale:1,format:'png'});await fs.writeFile(path.join(dir,spec.name+'.png'),new Uint8Array(await pic.arrayBuffer()));}
 const inspection=await wb.inspect({kind:'table',range:'集計サマリー!A5:C12',include:'values',tableMaxRows:8,tableMaxCols:3});await fs.writeFile(path.join(dir,'inspection.jsonl'),inspection.ndjson);
}
await fs.mkdir(path.dirname(target),{recursive:true});const output=await SpreadsheetFile.exportXlsx(wb);await output.save(target);
console.log(JSON.stringify({ok:true,responses:responses.length,sheets:specs.map(s=>s.name)}));
