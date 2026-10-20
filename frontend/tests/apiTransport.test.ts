import assert from 'node:assert/strict';
import test from 'node:test';
import {requestJsonWithPolicy,ApiError} from '../src/apiTransport.ts';
test('transient GET error retries but writes and forbidden responses do not',async()=>{
 const original=globalThis.fetch;let calls=0;
 try {
  globalThis.fetch=async()=>{calls++;return calls===1?new Response('',{status:502}):Response.json({ok:true});};
  assert.deepEqual(await requestJsonWithPolicy('/read',{}, {readTimeout:100,writeTimeout:100,retryDelay:0}),{ok:true});assert.equal(calls,2);
  calls=0;globalThis.fetch=async()=>{calls++;return new Response('',{status:503});};
  await assert.rejects(requestJsonWithPolicy('/write',{method:'POST'}),ApiError);assert.equal(calls,1);
  calls=0;globalThis.fetch=async()=>{calls++;return new Response('',{status:403});};
  await assert.rejects(requestJsonWithPolicy('/private'),ApiError);assert.equal(calls,1);
 }finally{globalThis.fetch=original;}
});
test('hung reads abort and finish with a useful error',async()=>{
 const original=globalThis.fetch;let calls=0;
 try{
  globalThis.fetch=async(_url,init)=>{calls++;return new Promise((_resolve,reject)=>init?.signal?.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError'))));};
  await assert.rejects(requestJsonWithPolicy('/hung',{}, {readTimeout:5,writeTimeout:5,retryDelay:0}),/не ответил вовремя/);assert.equal(calls,2);
 }finally{globalThis.fetch=original;}
});
