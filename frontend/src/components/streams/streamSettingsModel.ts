export interface StreamFormFields{camera_id:string;source_url:string;interval_minutes:number;weekdays:number[];window_start:string;window_end:string;daily_limit:number}
export function validateStreamForm(f:StreamFormFields,existing:boolean):string{
 if(!f.camera_id)return 'Выберите камеру';
 if(!existing&&!f.source_url.trim())return 'Укажите прямой адрес потока';
 if(f.source_url&&!/^(https?|rtsps?):\/\/[^\s]+$/i.test(f.source_url))return 'Укажите прямую ссылку HTTP(S) или RTSP(S)';
 if(!Number.isInteger(f.interval_minutes)||f.interval_minutes<1||f.interval_minutes>1440)return 'Интервал должен быть от 1 до 1440 минут';
 if(!f.weekdays.length)return 'Выберите хотя бы один день недели';
 if(Boolean(f.window_start)!==Boolean(f.window_end)||(f.window_start&&f.window_start===f.window_end))return 'Проверьте начало и окончание смены';
 if(!Number.isInteger(f.daily_limit)||f.daily_limit<1||f.daily_limit>1440)return 'Лимит должен быть от 1 до 1440 кадров';
 return '';
}
export function weeklyEstimate(interval:number,days:number,hours:number,limit:number){return interval>0?Math.min(Math.ceil(hours*60/interval),limit)*days:0;}
