import test from 'node:test';
import assert from 'node:assert/strict';
import { traceGraph } from '../src/components/traceGraphModel.ts';
const data:any={deviation:{title:'Дефицит',zone_name:'Участок'},quantity_checks:[],evidence:[],events:[]};
test('demo cameras converge into source and all stages connect to the result',()=>{const g=traceGraph(data,true);for(const id of ['camera-a','camera-b'])assert.ok(g.edges.some(e=>e.from===id&&e.to==='source'));for(const node of g.nodes)assert.ok(g.edges.some(e=>e.from===node.id||e.to===node.id));assert.equal(new Set(g.nodes.map(n=>n.id)).size,g.nodes.length);});
test('historical evidence does not invent a second camera',()=>{const g=traceGraph(data,false);assert.equal(g.nodes.filter(n=>n.id.startsWith('camera-')).length,1);assert.ok(g.nodes.find(n=>n.id==='camera-a')?.summary.includes('не сохранён'));});
test('graph nodes stay inside the canvas without overlapping',()=>{const g=traceGraph(data,true);for(const a of g.nodes){assert.ok(a.x>=0&&a.y>=0&&a.x+a.w<=g.width&&a.y+a.h<=g.height);for(const b of g.nodes){if(a.id===b.id)continue;assert.ok(a.x+a.w<=b.x||b.x+b.w<=a.x||a.y+a.h<=b.y||b.y+b.h<=a.y,`${a.id} overlaps ${b.id}`);}}});
import { edgeContribution } from '../src/components/traceGraphModel.ts';
test('path highlight turns off without making inactive branches solid',()=>{assert.deepEqual(edgeContribution('used','used',true),{active:true,highlighted:true});assert.deepEqual(edgeContribution('used','used',false),{active:true,highlighted:false});assert.deepEqual(edgeContribution('unused','used',true),{active:false,highlighted:false});assert.deepEqual(edgeContribution('unknown','used',true),{active:false,highlighted:false});});

test('actual camera identities come from evidence and multiple shots do not create fake cameras',()=>{
 const d:any={...data,evidence:[{camera_id:'cam-1',camera_name:'Котлован',observation_id:'one'},{camera_id:'cam-1',camera_name:'Котлован',observation_id:'two'},{camera_id:'cam-2',camera_name:'Въезд',observation_id:'three'}]};
 const g=traceGraph(d,false),c=g.nodes.filter(n=>n.id.startsWith('camera-'));
 assert.equal(c.length,2);assert.equal(c[0].title,'Котлован');assert.equal(c[0].state,'used');assert.ok(c[0].summary.includes('2'));
});

test('actual data flow runs recognition before comparison and unsupported historical links stay dashed',()=>{const g=traceGraph(data,false);assert.ok(g.edges.some(e=>e.from==='vision'&&e.to==='compare'));assert.ok(!g.edges.some(e=>e.from==='compare'&&e.to==='vision'));assert.deepEqual(edgeContribution('used','used',true,false),{active:false,highlighted:false});});
