import assert from "node:assert/strict";
import test from "node:test";
import { validateRegistration } from "../src/components/registrationValidation.ts";
const valid={full_name:"Иван Петров",email:"ivan@example.com",password:"Strong!Secret582",password_confirm:"Strong!Secret582"};
test("accepts Cyrillic and hyphenated names",()=>{assert.deepEqual(validateRegistration(valid),{});assert.deepEqual(validateRegistration({...valid,full_name:"Анна-Мария Петрова"}),{});});
test("rejects malformed fields and mismatch",()=>{const errors=validateRegistration({...valid,full_name:"Иван 123",email:"broken",password:"123",password_confirm:"456"});for(const field of ["full_name","email","password","password_confirm"])assert.ok(errors[field as keyof typeof errors]);});
test("normalization accepts surrounding whitespace without trimming passwords",()=>{assert.deepEqual(validateRegistration({...valid,email:" IVAN@EXAMPLE.COM ",full_name:" Иван   Петров "}),{});assert.ok(validateRegistration({...valid,password_confirm:valid.password+" "}).password_confirm);});
