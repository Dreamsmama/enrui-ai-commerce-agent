import { useState, type FormEvent } from 'react';
import { authApi } from '../api/client';

export default function Login() {
  const [registering, setRegistering] = useState(false);
  const [form, setForm] = useState({ tenant_name: '', tenant_code: '', name: '', email: '', password: '' });
  const [error, setError] = useState('');

  async function submit(event: FormEvent) {
    event.preventDefault(); setError('');
    try {
      const result = registering ? await authApi.register(form) : await authApi.login(form.email, form.password);
      localStorage.setItem('access_token', result.access_token);
      window.location.href = '/';
    } catch (err: any) {
      setError(err.response?.data?.detail || '操作失败');
    }
  }

  return <div className="min-h-screen grid place-items-center bg-[var(--bg)] p-6">
    <form className="panel p-8 w-full max-w-md space-y-4" onSubmit={submit}>
      <h1 className="font-display text-2xl">{registering ? '创建企业账号' : '登录 Enrui AI'}</h1>
      {registering && <>
        <label className="field"><span>企业名称</span><input required value={form.tenant_name} onChange={(e)=>setForm({...form,tenant_name:e.target.value})}/></label>
        <label className="field"><span>企业代码</span><input required pattern="[a-z0-9-]+" value={form.tenant_code} onChange={(e)=>setForm({...form,tenant_code:e.target.value})}/></label>
        <label className="field"><span>姓名</span><input required value={form.name} onChange={(e)=>setForm({...form,name:e.target.value})}/></label>
      </>}
      <label className="field"><span>邮箱</span><input type="email" required value={form.email} onChange={(e)=>setForm({...form,email:e.target.value})}/></label>
      <label className="field"><span>密码</span><input type="password" minLength={8} required value={form.password} onChange={(e)=>setForm({...form,password:e.target.value})}/></label>
      {error && <div className="text-sm text-red-600">{error}</div>}
      <button className="btn-primary w-full justify-center" type="submit">{registering ? '注册并进入' : '登录'}</button>
      <button className="text-sm text-[var(--accent)] w-full" type="button" onClick={()=>setRegistering(!registering)}>{registering ? '已有账号，去登录' : '首次使用，创建企业'}</button>
    </form>
  </div>;
}
