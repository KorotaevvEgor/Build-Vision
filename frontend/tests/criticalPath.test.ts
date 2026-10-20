import test from 'node:test';
import assert from 'node:assert/strict';
import { criticalEdge } from '../src/components/criticalPath.ts';
const s=(start:string,end:string,critical=true)=>({early_start_date:start,early_finish_date:end,is_critical:critical});
test('critical path includes tight FS links and excludes slack shortcuts',()=>{assert.equal(criticalEdge(s('2026-01-01','2026-01-02'),s('2026-01-03','2026-01-04')),true);assert.equal(criticalEdge(s('2026-01-01','2026-01-02'),s('2026-01-05','2026-01-06')),false);assert.equal(criticalEdge(s('2026-01-01','2026-01-02',false),s('2026-01-03','2026-01-04')),false);});
