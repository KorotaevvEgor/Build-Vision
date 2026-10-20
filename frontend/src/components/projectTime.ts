import tzLookup from "tz-lookup";

type ProjectLocation = {latitude?:number|null;longitude?:number|null;address?:string};
export function projectTimeZone(project:ProjectLocation):string {
  if(typeof project.latitude==="number"&&typeof project.longitude==="number"&&Number.isFinite(project.latitude)&&Number.isFinite(project.longitude)) {
    try { return tzLookup(project.latitude,project.longitude); } catch { /* Address fallback below. */ }
  }
  const address=(project.address??"").toLowerCase();
  if(address.includes("екатеринбург"))return "Asia/Yekaterinburg";
  if(address.includes("москва")||address.includes("московск"))return "Europe/Moscow";
  return "UTC";
}
export function formatProjectClock(now:Date,timeZone:string) {
  return {
    date:new Intl.DateTimeFormat("ru-RU",{timeZone,day:"numeric",month:"long"}).format(now),
    time:new Intl.DateTimeFormat("ru-RU",{timeZone,hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).format(now),
    zone:new Intl.DateTimeFormat("ru-RU",{timeZone,timeZoneName:"shortOffset"}).formatToParts(now).find(p=>p.type==="timeZoneName")?.value??timeZone,
  };
}
