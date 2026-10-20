import test from 'node:test';import assert from 'node:assert/strict';
import {adjustAnnotationBox,boxHandles} from '../src/components/annotationGeometry.ts';
import {correctionMoveIntent} from '../src/components/correctionWorkflow.ts';
test('right and corner handles expand only intended edges',()=>{assert.deepEqual(adjustAnnotationBox([10,20,40,60],'e',15,30,100,80),[10,20,55,60]);assert.deepEqual(adjustAnnotationBox([10,20,40,60],'nw',-5,-10,100,80),[5,10,40,60]);});
test('handles never cross or leave the image',()=>{assert.deepEqual(adjustAnnotationBox([10,20,40,60],'nw',100,100,100,80),[39,59,40,60]);assert.deepEqual(adjustAnnotationBox([10,20,40,60],'se',100,100,100,80),[10,20,100,80]);assert.equal(boxHandles([10,20,40,60]).length,8);});
test('moving preserves box size and clamps all sides',()=>{assert.deepEqual(adjustAnnotationBox([10,20,40,60],'move',200,-200,100,80),[70,0,100,40]);});
test('ready drop starts real training and never manually marks trained',()=>{assert.equal(correctionMoveIntent('ready','training',true),'train');assert.equal(correctionMoveIntent('ready','training',false),'forbidden');assert.equal(correctionMoveIntent('todo','training',true),'forbidden');assert.equal(correctionMoveIntent('ready','trained',true),'forbidden');assert.equal(correctionMoveIntent('ready','in_progress',true),'move');});
