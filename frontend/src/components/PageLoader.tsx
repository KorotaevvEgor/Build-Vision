import { Component, Suspense, type ReactNode } from "react";

export class PageLoader extends Component<{children:ReactNode},{failed:boolean}> {
  state={failed:false};
  static getDerivedStateFromError(){return {failed:true};}
  render(){
    if(this.state.failed)return <div className="sk-panel sk-panel--error" role="alert">Не удалось открыть раздел. Проверьте соединение. <button type="button" onClick={()=>window.location.reload()}>Повторить загрузку</button></div>;
    return <Suspense fallback={<div className="sk-panel" role="status">Загрузка раздела…</div>}>{this.props.children}</Suspense>;
  }
}
