import test from 'node:test';
import assert from 'node:assert/strict';
import {evidenceBoxes,type EvidenceDetection} from '../src/components/evidenceImageModel.ts';
const detection=(bbox:number[]):EvidenceDetection=>({id:1,class_key:'truck',label_ru:'Самосвал',confidence:.8,bbox,ambiguous:false,activity:'unknown',activity_reason:''});
test('pixel coordinates scale independently by original width and height',()=>{
 const [b]=evidenceBoxes([detection([100,50,300,200])],1000,500);
 assert.deepEqual([b.left,b.top,b.width,b.height],[10,10,20,30]);
});
test('off-frame coordinates clamp; reversed, non-finite and empty boxes are omitted',()=>{
 const boxes=evidenceBoxes([detection([-20,-10,1100,600]),detection([200,100,10,200]),detection([0,0,NaN,200]),detection([1100,0,1200,10]),detection([0,0,10])],1000,500);
 assert.equal(boxes.length,1);assert.deepEqual([boxes[0].left,boxes[0].top,boxes[0].width,boxes[0].height],[0,0,100,100]);
});
test('historical missing dimensions and missing detections never invent boxes',()=>{
 assert.deepEqual(evidenceBoxes([detection([0,0,10,10])],null,null),[]);
 assert.deepEqual(evidenceBoxes([],1000,500),[]);
});
