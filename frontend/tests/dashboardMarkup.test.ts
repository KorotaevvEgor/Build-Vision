import assert from "node:assert/strict";
import test from "node:test";
import { getDashboardDetections } from "../src/components/dashboardMarkup.ts";

const detector = {class_key:"truck",label_ru:"Грузовик",confidence:.9,bbox:[1,2,3,4],ambiguous:false,in_taxonomy:true,runner_up_class_key:null};
test("AI normalized boxes scale to the actual photo, replacing the visual detector layer",()=>{
  const result=getDashboardDetections({detections:[detector],ai_equipment:{available:true,items:[{class_key:"excavator",label_ru:"Экскаватор",confidence:.92,box:[.1,.2,.4,.8]}]}}, {width:1000,height:500});
  assert.deepEqual(result.map(x=>[x.class_key,x.bbox]),[["excavator",[100,100,400,400]]]);
});
test("successful empty AI result must not silently show YOLO objects",()=>{
  assert.deepEqual(getDashboardDetections({detections:[detector],ai_equipment:{available:true,items:[]}}, {width:1000,height:500}),[]);
});
test("without saved AI markup the existing detector remains available",()=>{
  assert.deepEqual(getDashboardDetections({detections:[detector]},null),[detector]);
});
test("invalid AI coordinates are not drawn",()=>{
  const result=getDashboardDetections({detections:[],ai_equipment:{available:true,items:[
    {class_key:"excavator",label_ru:"Экскаватор",confidence:.9,box:[.8,0,.2,1]},
    {class_key:"excavator",label_ru:"Экскаватор",confidence:.9,box:[0,0,Infinity,1]},
  ]}}, {width:1000,height:500});
  assert.deepEqual(result,[]);
});
