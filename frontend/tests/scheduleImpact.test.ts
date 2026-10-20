import test from 'node:test';
import assert from 'node:assert/strict';
import { scheduleImpact, scheduleSignal } from '../src/components/scheduleImpact.ts';
const s=(id:string,start:string,end:string,preds:string[]=[])=>({stage_id:id,planned_start_date:start,planned_end_date:end,predecessor_ids:preds,is_summary:false});
test('delay consumes actual calendar gap before moving successors',()=>{const r=scheduleImpact([s('a','2026-01-01','2026-01-02'),s('b','2026-01-06','2026-01-07',['a'])],'a',2);assert.equal(r.shifts.b,0);assert.equal(r.finishShift,0);});
test('delay propagates through dependent chain but not independent branch',()=>{const r=scheduleImpact([s('a','2026-01-01','2026-01-02'),s('b','2026-01-03','2026-01-04',['a']),s('c','2026-01-05','2026-01-06',['b']),s('d','2026-01-01','2026-01-02')],'a',3);assert.equal(r.shifts.b,3);assert.equal(r.shifts.c,3);assert.equal(r.shifts.d,0);assert.equal(r.finishShift,3);});
test('cycle makes scenario unavailable',()=>{assert.equal(scheduleImpact([s('a','2026-01-01','2026-01-02',['b']),s('b','2026-01-03','2026-01-04',['a'])],'a',1).available,false);});
test('absence of observations is not a green confirmation',()=>{assert.equal(scheduleSignal({state:'in_progress',delay_days:0,total_float_days:0,observation_count:0}).tone,'neutral');assert.equal(scheduleSignal({state:'overdue',delay_days:3,total_float_days:1,observation_count:1}).tone,'danger');assert.equal(scheduleSignal({state:'overdue',delay_days:1,total_float_days:2,observation_count:1}).tone,'warning');});

test('a join waits for the latest predecessor, not the sum of delays',()=>{const r=scheduleImpact([s('a','2026-01-01','2026-01-02'),s('b','2026-01-01','2026-01-05'),s('c','2026-01-06','2026-01-07',['a','b'])],'a',2);assert.equal(r.shifts.c,0);assert.equal(r.finishShift,0);});
test('preexisting overlapping dates are not attributed to the scenario',()=>{const r=scheduleImpact([s('a','2026-01-01','2026-01-04'),s('b','2026-01-02','2026-01-03',['a'])],'a',0);assert.equal(r.shifts.b,0);assert.equal(r.finishShift,0);});
