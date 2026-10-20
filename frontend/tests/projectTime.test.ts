import assert from "node:assert/strict";
import test from "node:test";
import { projectTimeZone, formatProjectClock } from "../src/components/projectTime.ts";
test("timezone follows project coordinates instead of the visitor",()=>{
  assert.equal(projectTimeZone({latitude:55.67069,longitude:37.58131,address:"Москва"}),"Europe/Moscow");
  assert.equal(projectTimeZone({latitude:56.8524,longitude:60.5896,address:"Екатеринбург"}),"Asia/Yekaterinburg");
});
test("local calendar date changes at the project's midnight",()=>{
  const instant=new Date("2026-10-15T22:30:00Z");
  assert.equal(formatProjectClock(instant,"Europe/Moscow").time,"01:30");
  assert.equal(formatProjectClock(instant,"Asia/Yekaterinburg").time,"03:30");
  assert.match(formatProjectClock(instant,"Europe/Moscow").date,/16/);
});
