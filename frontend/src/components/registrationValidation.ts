export interface RegistrationValues {full_name:string;email:string;password:string;password_confirm:string;}
export type RegistrationErrors = Partial<Record<keyof RegistrationValues,string>>;
export function validateRegistration(values:RegistrationValues):RegistrationErrors {
 const errors:RegistrationErrors={};
 const name=values.full_name.trim().replace(/\s+/g," ");
 if(name.length>150||!/^\p{L}+(?:[ .’'-]+\p{L}+)+$/u.test(name)) errors.full_name="Введите имя и фамилию буквами, без цифр.";
 const email=values.email.trim();
 if(email.length>254||!/^([^\s@]+)@([^\s@]+)\.[^\s@.]+$/.test(email)) errors.email="Введите корректный email, например name@company.ru.";
 if(values.password.length<8||values.password.length>128) errors.password="Пароль должен содержать от 8 до 128 символов.";
 else if(/^\d+$/.test(values.password)) errors.password="Пароль не должен состоять только из цифр.";
 if(values.password!==values.password_confirm) errors.password_confirm="Пароли не совпадают.";
 return errors;
}
