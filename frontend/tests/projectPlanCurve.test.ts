import test from "node:test";
import assert from "node:assert/strict";
import {projectPlanCurve} from "../src/components/projectPlanCurve.ts";
test("parallel tasks remain chronological and do not complete before the last finish",()=>{
 const curve=projectPlanCurve([{planned_start_date:"2026-01-01",planned_end_date:"2026-01-31"},{planned_start_date:"2026-01-10",planned_end_date:"2026-01-20"}]);
 assert.equal(curve.at(-1)?.date,"2026-01-31");assert.equal(curve.at(-1)?.percent,100);
 assert.ok(curve.find(p=>p.date==="2026-01-20")!.percent<100);
 for(let i=1;i<curve.length;i++){assert.ok(curve[i].date>curve[i-1].date);assert.ok(curve[i].percent>=curve[i-1].percent);}
});
test("single-day tasks and empty input",()=>{assert.deepEqual(projectPlanCurve([]),[]);assert.equal(projectPlanCurve([{planned_start_date:"2026-01-01",planned_end_date:"2026-01-01"}]).at(-1)?.percent,100);});

test("a gap between works is flat",()=>{const curve=projectPlanCurve([{planned_start_date:"2026-01-01",planned_end_date:"2026-01-03"},{planned_start_date:"2026-01-10",planned_end_date:"2026-01-12"}]);assert.equal(curve.find(p=>p.date==="2026-01-03")?.percent,50);assert.equal(curve.find(p=>p.date==="2026-01-09")?.percent,50);});
