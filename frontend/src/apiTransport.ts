export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status:number,message:string,detail?:unknown) { super(message);this.status=status;this.detail=detail; }
}

/** Retry only reads. Writes may already have succeeded when a connection breaks. */
export async function requestJsonWithPolicy<T>(url:string,init:RequestInit={},policy={readTimeout:12000,writeTimeout:120000,retryDelay:300}):Promise<T> {
  const read=["GET","HEAD"].includes((init.method??"GET").toUpperCase());
  for(let attempt=0;attempt<(read?2:1);attempt++) {
    const controller=new AbortController();
    const abort=()=>controller.abort();
    init.signal?.addEventListener("abort",abort,{once:true});
    if(init.signal?.aborted)controller.abort();
    const timer=setTimeout(abort,read?policy.readTimeout:policy.writeTimeout);
    try {
      const response=await fetch(url,{...init,signal:controller.signal});
      if(!response.ok) {
        const body=await response.text();let detail:unknown;
        try{detail=(JSON.parse(body) as {detail?:unknown}).detail;}catch{ /* Proxy errors may be HTML. */ }
        throw new ApiError(response.status,typeof detail==="string"?detail:`Сервер временно недоступен (${response.status}). Повторите попытку.`,detail);
      }
      return await response.json() as T;
    } catch(error) {
      const retry=read&&attempt===0&&!init.signal?.aborted&&(!(error instanceof ApiError)||[502,503,504].includes(error.status));
      if(!retry) {
        if(controller.signal.aborted&&!init.signal?.aborted)throw new Error("Сервер не ответил вовремя. Проверьте соединение и повторите попытку.");
        throw error;
      }
    } finally { clearTimeout(timer);init.signal?.removeEventListener("abort",abort); }
    await new Promise(resolve=>setTimeout(resolve,policy.retryDelay));
  }
  throw new Error("Не удалось загрузить данные. Повторите попытку.");
}
