import {test} from 'node:test';
import assert from 'node:assert/strict';
import {scenarioFinish} from '../src/components/forecastScenarioModel.ts';
const stages=[
 {stage_id:'a',planned_start_date:'2027-01-01',planned_end_date:'2027-01-10',predecessor_ids:[],is_summary:false},
 {stage_id:'b',planned_start_date:'2027-01-11',planned_end_date:'2027-01-20',predecessor_ids:['a','side'],is_summary:false},
 {stage_id:'side',planned_start_date:'2027-01-01',planned_end_date:'2027-01-04',predecessor_ids:[],is_summary:false},
];
test('delay inside reserve does not move finish; excess propagates',()=>{
 assert.equal(scenarioFinish(stages,{side:6}),'2027-01-20');
 assert.equal(scenarioFinish(stages,{side:7}),'2027-01-21');
});
test('serial delays accumulate and mitigation recovers exact days',()=>{
 assert.equal(scenarioFinish(stages,{a:12,b:6}),'2027-02-07');
 assert.equal(scenarioFinish(stages,{a:4,b:3}),'2027-01-27');
});
test('input order does not affect result or mutate source',()=>{
 const copy=JSON.stringify(stages);
 assert.equal(scenarioFinish([...stages].reverse(),{a:1}),'2027-01-21');
 assert.equal(JSON.stringify(stages),copy);
});
test('missing links and cycles fail instead of presenting a fabricated date',()=>{
 assert.throws(()=>scenarioFinish([{...stages[0],predecessor_ids:['missing']}],{}));
 assert.throws(()=>scenarioFinish([{...stages[0],predecessor_ids:['a']}],{}));
});
