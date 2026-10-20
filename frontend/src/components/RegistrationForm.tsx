import { useState } from "react";
import type { FormEvent } from "react";
import { ApiError, submitRegistration } from "../api";
import { validateRegistration } from "./registrationValidation";
import type { RegistrationValues, RegistrationErrors } from "./registrationValidation";

export function RegistrationForm({onLogin}:{onLogin:()=>void}) {
 const [values,setValues]=useState<RegistrationValues>({full_name:"",email:"",password:"",password_confirm:""});
 const [errors,setErrors]=useState<RegistrationErrors>({});
 const [error,setError]=useState("");
 const [busy,setBusy]=useState(false);
 const [show,setShow]=useState(false);
 const [result,setResult]=useState<{status:"sent"|"already_sent";email:string}|null>(null);
 const fields=[{key:"full_name",label:"ФИО",placeholder:"Иван Петров",autoComplete:"name"},{key:"email",label:"Email",placeholder:"name@company.ru",autoComplete:"email"},{key:"password",label:"Пароль",placeholder:"Не менее 8 символов",autoComplete:"new-password"},{key:"password_confirm",label:"Подтверждение пароля",placeholder:"Повторите пароль",autoComplete:"new-password"}] as const;
 const submit=async(event:FormEvent)=>{
  event.preventDefault();setError("");
  const next=validateRegistration(values);setErrors(next);
  if(Object.keys(next).length) return;
  setBusy(true);
  try {setResult(await submitRegistration(values));setValues(v=>({...v,password:"",password_confirm:""}));}
  catch(err) {
   if(err instanceof ApiError && err.status===422 && err.detail && typeof err.detail==="object" && "fields" in err.detail) setErrors((err.detail as {fields:RegistrationErrors}).fields);
   else setError(err instanceof Error ? err.message : "Не удалось отправить заявку. Повторите попытку.");
  } finally {setBusy(false);}
 };
 if(result) return <section className="sk-registration-result" role="status" aria-live="polite">
  <div className="sk-registration-result__icon" aria-hidden="true"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><rect x="3" y="5" width="18" height="14" rx="3"/><path d="m4 7 8 6 8-6"/></svg></div>
  <h1>{result.status==="already_sent"?"Письмо уже отправлено":"Письмо отправлено"}</h1>
  <p>{result.status==="already_sent"?"На этот адрес уже отправлено письмо с дальнейшими указаниями. Повторная заявка не требуется.":"Мы отправили письмо с дальнейшими указаниями по регистрации на вашу почту."}</p>
  <strong className="sk-registration-result__email">{result.email}</strong>
  <p className="sk-registration-result__muted">Проверьте входящие письма и папку «Спам».</p>
  <button type="button" className="sk-login__submit" onClick={onLogin}>Вернуться ко входу</button>
  <button type="button" className="sk-registration-back" onClick={()=>setResult(null)}>Изменить данные</button>
 </section>;
 return <form className="sk-login__form sk-registration" onSubmit={submit} noValidate>
  <div className="sk-login__header"><span className="sk-login__eyebrow">BuildVision</span><h1 className="sk-login__title">Регистрация</h1><p className="sk-login__hint">Заполните данные для создания аккаунта</p></div>
  {fields.map(field=><div className="sk-login__field" key={field.key}>
   <label htmlFor={`register-${field.key}`}>{field.label}</label>
   <input id={`register-${field.key}`} name={field.key} type={field.key==="email"?"email":field.key.startsWith("password")&&!show?"password":"text"} value={values[field.key]} autoComplete={field.autoComplete} placeholder={field.placeholder} maxLength={field.key==="email"?254:field.key==="full_name"?150:128} disabled={busy} required aria-invalid={Boolean(errors[field.key])} aria-describedby={errors[field.key]?`register-error-${field.key}`:undefined}
    onChange={e=>{setValues(v=>({...v,[field.key]:e.target.value}));setErrors(v=>({...v,[field.key]:undefined}));}}
    onBlur={()=>setErrors(v=>({...v,[field.key]:validateRegistration(values)[field.key]}))}/>
   {errors[field.key]&&<span className="sk-registration-field-error" id={`register-error-${field.key}`} role="alert">{errors[field.key]}</span>}
  </div>)}
  <label className="sk-registration-show"><input type="checkbox" checked={show} onChange={e=>setShow(e.target.checked)}/>Показать пароль</label>
  {error&&<p className="sk-registration-field-error" role="alert">{error}</p>}
  <button type="submit" className="sk-login__submit" disabled={busy}>{busy?"Отправляем…":"Зарегистрироваться"}</button>
  <p className="sk-login__footer">Доступ к проектам выдаёт администратор</p>
 </form>;
}
