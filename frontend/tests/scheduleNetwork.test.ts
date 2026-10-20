import test from 'node:test';
import assert from 'node:assert/strict';
import { networkLayout } from '../src/components/scheduleNetworkLayout.ts';
const stage=(stage_id:string,predecessor_ids:string[]=[])=>({stage_id,predecessor_ids,planned_start_date:'2026-01-01'});
test('branches share a rank and joins follow all predecessors',()=>{
 const result=networkLayout([stage('a'),stage('b',['a']),stage('c',['a']),stage('d',['b','c'])]);
 const ranks=Object.fromEntries(result.nodes.map(n=>[n.stage.stage_id,n.rank]));
 assert.deepEqual(ranks,{a:0,b:1,c:1,d:2});assert.equal(result.edges.length,4);assert.equal(result.cyclic,false);
});
test('filtering does not invent links across hidden stages',()=>{
 const result=networkLayout([stage('a'),stage('c',['b'])]);
 assert.equal(result.edges.length,0);assert.equal(result.hiddenPredecessors,1);
});
test('cycles remain inspectable and cannot hang layout',()=>{
 const result=networkLayout([stage('a',['b']),stage('b',['a']),stage('c',['b'])]);
 assert.equal(result.cyclic,true);assert.equal(result.nodes.length,3);assert.equal(result.edges.length,3);
 assert.equal(new Set(result.nodes.map(n=>`${n.x},${n.y}`)).size,3);
});
test('empty schedule has a finite canvas',()=>{
 const result=networkLayout([]);assert.equal(result.nodes.length,0);assert.ok(Number.isFinite(result.width));assert.ok(Number.isFinite(result.height));
});
