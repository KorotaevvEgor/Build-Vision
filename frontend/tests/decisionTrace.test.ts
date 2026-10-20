import test from 'node:test';
import assert from 'node:assert/strict';
import { decisionTrace } from '../src/components/decisionTraceModel.ts';
const legacy:any={deviation:{title:'Не хватает техники',work_name:'Котлован',zone_name:'Площадка'},quantity_checks:[],evidence:[],events:[]};
test('historical gaps never become invented observations or module participation',()=>{const t=decisionTrace(legacy);assert.equal(t.find(x=>x.id==='vision')?.state,'unknown');assert.equal(t.find(x=>x.id==='learning')?.state,'unknown');assert.equal(t.find(x=>x.id==='weather')?.state,'unknown');assert.equal(t.find(x=>x.id==='proof')?.state,'unknown');assert.ok(!JSON.stringify(t).includes('Qwen выполнила'));});
test('saved quantities and comparable series explain the result without claiming physical delay',()=>{const d:any={...legacy,methodology:{rule_fingerprint:'saved-rule',coverage_verified:true,counted_detections:[{label_ru:'Самосвал',index:0}],excluded_detections:[{label_ru:'Самосвал',index:1,reason:'Стоянка'}]},quantity_checks:[{label_ru:'Самосвал',required_qty:6,actual_qty:2}],deviation:{...legacy.deviation,proof:{level:'repeated_observation',independent_count:2,sequence_count:2,profile:{min_frames:2},records:[]}}};const t=decisionTrace(d);assert.ok(JSON.stringify(t).includes('6 / 2 / 4'));assert.equal(t.find(x=>x.id==='proof')?.state,'used');assert.ok(JSON.stringify(t).includes('не доказывает'));});
test('scenario is explicit and does not mutate live evidence',()=>{const before=JSON.stringify(legacy);const t=decisionTrace(legacy,true);assert.equal(JSON.stringify(legacy),before);assert.ok(t.every(x=>x.demo));assert.equal(t.find(x=>x.id==='learning')?.state,'unused');assert.equal(t.find(x=>x.id==='weather')?.state,'unused');assert.ok(JSON.stringify(t).includes('6 / 2 / 4'));});


test('saved real detections explain Vision even for a historical frame without allocation metadata',()=>{
 const t=decisionTrace({...legacy,evidence:[{observation_id:'o',detections:[{class_key:'dump_truck',label_ru:'Самосвал',confidence:.9,bbox:[0,0,10,10]}]}]} as any);
 assert.equal(t.find(x=>x.id==='vision')?.state,'used');assert.ok(t.find(x=>x.id==='vision')?.summary.includes('1'));assert.ok(t.find(x=>x.id==='vision')?.result.includes('не восстановлено'));
});
test('learning participation uses saved per-call execution rather than current model state',()=>{
 const d:any={...legacy,methodology:{rule:{detector:{execution:{correction:{status:'participated',version_id:7,classified_count:2,changed_count:1}}}}}};
 const t=decisionTrace(d);assert.equal(t.find(x=>x.id==='learning')?.state,'used');assert.ok(t.find(x=>x.id==='learning')?.result.includes('1'));
 const unused=decisionTrace({...d,methodology:{rule:{detector:{execution:{correction:{status:'unused',reason:'Нет опубликованной модели проекта'}}}}}} as any);
 assert.equal(unused.find(x=>x.id==='learning')?.state,'unused');
});
