import test from 'node:test';
import assert from 'node:assert/strict';
import {assessScenario,walkthroughCases,assessCase,selectWalkthroughCase} from '../src/components/walkthroughModel.ts';
test('only independent usable repetition confirms visible shortage',()=>{
 assert.equal(assessScenario('persistent').status,'confirmed');
 assert.equal(assessScenario('duplicate').status,'preliminary');
 assert.equal(assessScenario('obscured').status,'insufficient');
 assert.equal(assessScenario('restored').status,'clear');
 assert.equal(assessScenario('persistent').deficit,4);
 assert.equal(assessScenario('restored').deficit,0);
 assert.equal(assessScenario('obscured').deficit,null);
 assert.equal(assessScenario('duplicate').actual,null);
});
test('six cases use technology-specific requirements and evidence',()=>{
 assert.equal(walkthroughCases.length,6);
 assert.equal(new Set(walkthroughCases.map(c=>c.work)).size,6);
 for(const c of walkthroughCases){
  assert.equal(c.steps.length,7);
  assert.equal(c.outcomes.length,4);
  assert.ok(c.actions.length>=3);
  for(const state of ['persistent','restored','obscured','duplicate'] as const){
   const r=assessCase(c.id,state);
   assert.ok(r.title.length>15);
   assert.ok(r.explanation.length>40);
  }
 }
 assert.equal(assessCase('trucks','persistent').deficit,4);
 assert.equal(assessCase('excavator','persistent').deficit,1);
 assert.equal(assessCase('crane','persistent').deficit,1);
 assert.equal(assessCase('roller','persistent').deficit,1);
});
test('uncertainty and weather never become confirmed equipment deficits',()=>{
 assert.equal(assessCase('recognition','persistent').deficit,null);
 assert.equal(assessCase('recognition','persistent').status,'insufficient');
 assert.equal(assessCase('recognition','restored').deficit,0);
 assert.equal(assessCase('weather','persistent').status,'risk');
 assert.equal(assessCase('weather','persistent').deficit,null);
 assert.equal(assessCase('weather','obscured').status,'insufficient');
 for(const c of walkthroughCases){
  assert.equal(assessCase(c.id,'duplicate').accepted,false);
  assert.equal(assessCase(c.id,'obscured').deficit,null);
 }
});
test('case selection follows alert content instead of always choosing trucks',()=>{
 assert.equal(selectWalkthroughCase({kind:'weather_risk',classKeys:['dump_truck']}),'weather');
 assert.equal(selectWalkthroughCase({classKeys:['excavator']}),'excavator');
 assert.equal(selectWalkthroughCase({classKeys:['mobile_crane']}),'crane');
 assert.equal(selectWalkthroughCase({title:'Не обнаружен каток'}),'roller');
 assert.equal(selectWalkthroughCase({title:'Неоднозначное распознавание'}),'recognition');
 assert.equal(selectWalkthroughCase({classKeys:['dump_truck']}),'trucks');
 assert.equal(selectWalkthroughCase({title:'Автокран вне зоны',classKeys:['dump_truck']}),'crane');
});
