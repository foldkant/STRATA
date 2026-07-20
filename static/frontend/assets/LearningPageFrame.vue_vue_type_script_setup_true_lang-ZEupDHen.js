import{j as y,C as $,d as P,o as N,E as H,a as O,b as Y,r as F,i as X}from"./index-Bl5hpkEk.js";function V(c){return y(`/api/v1/teacher/lessons/${c}/learning-pages/`)}function J(c,l,f="auto"){return y(`/api/v1/teacher/lessons/${c}/learning-pages/`,{method:"POST",body:$({direction:l,generation_mode:f})})}function U(c,l,f="auto"){return y(`/api/v1/teacher/learning-pages/${c}/revise/`,{method:"POST",body:$({direction:l,generation_mode:f})})}function K(c,l){const f=l?`?classroom_session=${l}`:"";return y(`/api/v1/teacher/learning-pages/${c}/responses/${f}`)}function Z(c,l="unknown"){return y(`/api/v1/learning-pages/${c}/?presentation=${l}`)}function G(c,l,f){return y(`/api/v1/student/learning-pages/${c}/submit/`,{method:"POST",body:$({form_id:l,answers:f})})}function Q(c,l){return y(`/api/v1/student/learning-pages/${c}/blocks/viewed/`,{method:"POST",body:$({block_id:l.blockId,block_type:l.blockType,visible_ms:l.visibleMs,visibility_ratio:l.visibilityRatio})})}const W=["srcdoc","title"],h="c3RyYXRhLWxlYXJuaW5nLXBhZ2U=",ee=P({__name:"LearningPageFrame",props:{page:{},interactive:{type:Boolean,default:!1}},emits:["submit","blockViewed"],setup(c,{expose:l,emit:f}){const v=c,_=f,x=F(null);function a(e){return String(e??"").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#039;")}function d(e){return a(e).replaceAll(`
`,"<br>")}function E(e){const t=new TextEncoder().encode(e);let i="";const n=32768;for(let r=0;r<t.length;r+=n)i+=String.fromCharCode(...t.subarray(r,r+n));return btoa(i)}function A(e,t){const i=a(e.id),n=a(`${t}:${e.id}`),r=e.required?' data-required="true"':"",s=v.interactive?"":" disabled",u=a(e.placeholder||""),m=`<span class="field-label">${a(e.label)}${e.required?"<b>*</b>":""}</span>`;if(e.type==="single"||e.type==="scale"){const b=(e.options||[]).map((p,o)=>`
      <label class="choice-option">
        <input data-field="${i}"${r} type="radio" name="${n}" value="${a(p)}"${s}>
        <span>${e.type==="scale"?`<strong>${o+1}</strong>`:""}${a(p)}</span>
      </label>`).join("");return`<fieldset class="learning-field ${e.type==="scale"?"scale-field":""}"><legend>${m}</legend><div class="choice-grid">${b}</div></fieldset>`}if(e.type==="multiple"){const b=(e.options||[]).map(p=>`
      <label class="choice-option">
        <input data-field="${i}"${r} type="checkbox" name="${n}" value="${a(p)}"${s}>
        <span>${a(p)}</span>
      </label>`).join("");return`<fieldset class="learning-field"><legend>${m}</legend><div class="choice-grid">${b}</div></fieldset>`}if(e.type==="select"){const b=(e.options||[]).map(p=>`<option value="${a(p)}">${a(p)}</option>`).join("");return`<label class="learning-field">${m}<select data-field="${i}"${r}${s}><option value="">请选择</option>${b}</select></label>`}if(e.type==="long_text")return`<label class="learning-field">${m}<textarea data-field="${i}"${r} maxlength="8000" rows="5" placeholder="${u}"${s}></textarea></label>`;if(e.type==="number"){const b=e.min===null||e.min===void 0?"":` min="${a(e.min)}"`,p=e.max===null||e.max===void 0?"":` max="${a(e.max)}"`;return`<label class="learning-field">${m}<input data-field="${i}"${r} type="number"${b}${p} placeholder="${u}"${s}></label>`}return`<label class="learning-field">${m}<input data-field="${i}"${r} type="text" maxlength="1000" placeholder="${u}"${s}></label>`}function B(e){const t=["process","timeline","bars","binary"].includes(e.visualization_type||"")?e.visualization_type:"process",i=(e.items||[]).filter(o=>typeof o=="object"&&"label"in o&&"detail"in o);if(i.length<2)return"";const n=Math.min(Math.max(Number(e.duration_ms||5e3),1500),15e3),r=Math.max(Math.floor(n/i.length),120),s=Math.min(Math.max(Math.floor(r*.72),280),850),u=i.map(o=>Number(o.value||0)),m=Math.max(...u,1),b=e.description?`<p class="visual-description">${d(e.description)}</p>`:"",p=i.map((o,q)=>{const k=["blue","green","cyan","amber","red","indigo"].includes(o.tone)?o.tone:"blue",w=`--item-delay:${q*r}ms;--motion-duration:${s}ms`;if(t==="bars"){const z=Number(o.value||0),M=Math.min(Math.max(z*100/m,0),100);return`<article class="visual-item tone-${k}" style="${w};--bar-width:${M}%"><span>${a(o.label)}</span><div><i></i></div><strong>${a(z)}</strong>${o.detail?`<small>${d(o.detail)}</small>`:""}</article>`}if(t==="binary"){const M=[...String(o.code||o.value||"")].slice(0,32).map((R,C)=>`<i style="--digit-delay:${C*45}ms">${a(R)}</i>`).join("");return`<article class="visual-item tone-${k}" style="${w}"><span>${a(o.label)}</span><strong class="binary-code">${M||"<i>-</i>"}</strong>${o.detail?`<small>${d(o.detail)}</small>`:""}</article>`}return`<article class="visual-item tone-${k}" style="${w}"><em>${q+1}</em><div><strong>${a(o.label)}</strong>${o.code?`<code>${a(o.code)}</code>`:""}${o.detail?`<small>${d(o.detail)}</small>`:""}</div></article>`}).join("");return`<section class="page-block visualization-block visual-type-${t}" data-visualization data-duration="${n}" data-autoplay="${e.autoplay!==!1}" data-loop="${!!e.loop}"><header><div>${e.title?`<h2>${a(e.title)}</h2>`:""}${b}</div><div class="visual-controls"><button type="button" data-visual-play>播放动画</button><button type="button" data-visual-replay>重新播放</button></div></header><div class="visual-stage">${p}</div></section>`}function j(e){const t=Math.min(Math.max(Number(e.height||520),280),900),i=String(e.css||"").replace(/<\/style/gi,"<\\/style"),n=String(e.javascript||"").replace(/<\/script/gi,"<\\/script"),r=`<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${h}'; img-src data: blob:; media-src data: blob:; connect-src 'none'; frame-src 'none'; object-src 'none'; form-action 'none'; base-uri 'none'">
  <style>*{box-sizing:border-box}html,body{margin:0;min-height:100%;font-family:Inter,'Microsoft YaHei',Arial,sans-serif;color:#172033;background:#fff}button,input,select,textarea{font:inherit}${i}</style>
</head>
<body>
<div id="__strata_runtime_error" role="alert" hidden></div>
${String(e.html||"")}
<script nonce="${h}">
(() => {
  const errorBox = document.getElementById('__strata_runtime_error');
  const showError = (message) => {
    if (!errorBox) return;
    errorBox.hidden = false;
    errorBox.textContent = '动画运行失败：' + String(message || '未知脚本错误');
  };
  addEventListener('error', (event) => showError(event.message));
  addEventListener('unhandledrejection', (event) => showError(event.reason?.message || event.reason));
})();
<\/script>
<script nonce="${h}">${n}<\/script>
</body>
</html>`,s=`data:text/html;charset=utf-8;base64,${E(r)}`,u=e.description?`<p class="visual-description">${d(e.description)}</p>`:"";return`<section class="page-block interactive-block"><header><div>${e.title?`<h2>${a(e.title)}</h2>`:""}${u}</div><button type="button" data-interactive-reload>重新运行</button></header><iframe class="interactive-frame" title="${a(e.title||"交互动画")}" sandbox="allow-scripts" referrerpolicy="no-referrer" loading="lazy" style="height:${t}px" src="${a(s)}"></iframe></section>`}function g(e,t,i){const n=a(t.id||`block_${i+1}`),r=a(t.type);return e.replace("<section ",`<section data-learning-block-id="${n}" data-learning-block-type="${r}" `)}function L(e,t){const i=e.title?`<h2>${a(e.title)}</h2>`:"";if(e.type==="content")return g(`<section class="page-block content-block">${i}<p>${d(e.body)}</p></section>`,e,t);if(e.type==="callout")return g(`<section class="page-block callout-block tone-${a(e.tone||"info")}">${i}<p>${d(e.body)}</p></section>`,e,t);if(e.type==="list"){const n=(e.items||[]).filter(r=>typeof r=="string").map(r=>`<li>${d(r)}</li>`).join("");return g(`<section class="page-block list-block">${i}<ul>${n}</ul></section>`,e,t)}if(e.type==="steps"||e.type==="cards"){const n=(e.items||[]).filter(r=>typeof r=="object").map((r,s)=>`
      <article><em>${e.type==="steps"?s+1:""}</em><div><h3>${a(r.title)}</h3><p>${d(r.body)}</p></div></article>`).join("");return g(`<section class="page-block ${e.type}-block">${i}<div class="${e.type}-grid">${n}</div></section>`,e,t)}if(e.type==="table"){const n=(e.headers||[]).map(s=>`<th>${a(s)}</th>`).join(""),r=(e.rows||[]).map(s=>`<tr>${s.map(u=>`<td>${d(u)}</td>`).join("")}</tr>`).join("");return g(`<section class="page-block table-block">${i}<div class="table-wrap"><table><thead><tr>${n}</tr></thead><tbody>${r}</tbody></table></div></section>`,e,t)}if(e.type==="code")return g(`<section class="page-block code-block">${i}<span>${a(e.language||"text")}</span><pre><code>${a(e.code||"")}</code></pre></section>`,e,t);if(e.type==="visualization")return g(B(e),e,t);if(e.type==="interactive")return g(j(e),e,t);if(e.type==="form"){const n=a(e.form_id||`form_${t+1}`),r=(e.fields||[]).map(m=>A(m,e.form_id||`form_${t+1}`)).join(""),s=e.description?`<p class="form-description">${d(e.description)}</p>`:"",u=v.interactive?`<button type="button" data-learning-submit="${n}">${a(e.submit_label||"提交")}</button>`:'<button type="button" disabled>教师预览</button>';return g(`<section class="page-block form-block">${i}${s}<form data-learning-form="${n}" novalidate>${r}<footer>${u}<span data-form-status="${n}"></span></footer></form></section>`,e,t)}return""}const T=X(()=>{const e=v.page.schema,t=(e.blocks||[]).map(L).join("");return`<!doctype html>
<html lang="zh-CN" data-accent="${a(e.accent||"blue")}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${h}'; img-src data:; connect-src 'none'; media-src 'none'; font-src 'none'; frame-src data:; object-src 'none'; form-action 'none'; base-uri 'none'">
  <title>${a(e.title)}</title>
  <style>
    :root{--accent:#1f6feb;--accent-soft:#eaf2ff;--ink:#172033;--muted:#64748b;--line:#dbe4ef;--surface:#fff;--bg:#f5f8fc;--success:#15803d;--warning:#b45309;--danger:#b91c1c;font-family:Inter,"Microsoft YaHei",Arial,sans-serif;color:var(--ink);background:var(--bg);font-size:16px}
    html[data-accent="green"]{--accent:#15803d;--accent-soft:#ecfdf3}html[data-accent="cyan"]{--accent:#087f8c;--accent-soft:#ecfeff}html[data-accent="amber"]{--accent:#b45309;--accent-soft:#fff7ed}html[data-accent="red"]{--accent:#b91c1c;--accent-soft:#fef2f2}html[data-accent="indigo"]{--accent:#4338ca;--accent-soft:#eef2ff}
    *{box-sizing:border-box}body{margin:0;min-height:100vh;background:var(--bg)}main{width:min(1040px,calc(100% - 32px));margin:0 auto;padding:34px 0 64px}.page-head{padding:0 4px 24px;border-bottom:1px solid var(--line);margin-bottom:20px}.page-head span{display:inline-block;color:var(--accent);font-size:13px;font-weight:700;margin-bottom:8px}.page-head h1{font-size:clamp(28px,4vw,44px);line-height:1.15;margin:0 0 10px}.page-head p{margin:0;color:var(--muted);line-height:1.7}.page-block{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:22px;margin:16px 0;box-shadow:0 4px 18px rgba(15,23,42,.04)}h2{font-size:20px;margin:0 0 12px}h3{font-size:16px;margin:0 0 6px}p{line-height:1.75;margin:0;color:#334155}.callout-block{border-left:5px solid var(--accent);background:var(--accent-soft)}.tone-success{border-left-color:var(--success);background:#f0fdf4}.tone-warning{border-left-color:var(--warning);background:#fffbeb}.tone-danger{border-left-color:var(--danger);background:#fef2f2}ul{margin:0;padding-left:24px;display:grid;gap:9px;line-height:1.65}.steps-grid,.cards-grid{display:grid;gap:12px}.steps-grid article,.cards-grid article{display:flex;gap:14px;border:1px solid var(--line);border-radius:7px;padding:15px}.steps-grid em{flex:none;width:30px;height:30px;border-radius:50%;display:grid;place-items:center;background:var(--accent);color:#fff;font-style:normal;font-weight:700}.cards-grid{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}.cards-grid em{display:none}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse}th,td{text-align:left;border:1px solid var(--line);padding:11px;line-height:1.55}th{background:#f8fafc}pre{margin:0;overflow:auto;padding:16px;border-radius:7px;background:#111827;color:#e5e7eb;line-height:1.6}.code-block>span{display:block;color:var(--muted);font-size:12px;margin:-8px 0 8px}.form-description{margin-bottom:18px}.learning-field{display:block;border-top:1px solid #edf1f6;padding:17px 0}.learning-field:first-child{border-top:0}.field-label{display:block;font-weight:700;margin-bottom:9px}.field-label b{color:var(--danger);margin-left:4px}fieldset{margin:0;border:0}.choice-grid{display:flex;flex-wrap:wrap;gap:9px}.choice-option{position:relative}.choice-option input{position:absolute;opacity:0;pointer-events:none}.choice-option span{display:flex;align-items:center;gap:7px;min-height:42px;padding:9px 14px;border:1px solid var(--line);border-radius:6px;background:#fff;cursor:pointer}.choice-option input:checked+span{border-color:var(--accent);background:var(--accent-soft);color:var(--accent);box-shadow:0 0 0 1px var(--accent)}.choice-option input:focus-visible+span{outline:2px solid var(--accent);outline-offset:2px}.choice-option input:disabled+span{cursor:default;opacity:.72}.scale-field .choice-grid{display:grid;grid-template-columns:repeat(5,minmax(54px,1fr))}.scale-field .choice-option span{justify-content:center;flex-direction:column}.scale-field .choice-option strong{font-size:20px}input[type="text"],input[type="number"],select,textarea{width:100%;border:1px solid var(--line);border-radius:6px;padding:11px 12px;background:#fff;color:var(--ink);font:inherit}textarea{resize:vertical}input:focus,select:focus,textarea:focus{outline:2px solid color-mix(in srgb,var(--accent) 25%,transparent);border-color:var(--accent)}form footer{display:flex;align-items:center;gap:14px;padding-top:16px}form footer button{border:0;border-radius:6px;background:var(--accent);color:#fff;font:inherit;font-weight:700;padding:11px 20px;cursor:pointer}form footer button:disabled{background:#94a3b8;cursor:not-allowed}form footer span{color:var(--muted);font-size:14px}.field-invalid .field-label{color:var(--danger)}
    .visualization-block{overflow:hidden}.visualization-block>header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:18px}.visualization-block h2{margin-bottom:5px}.visual-description{color:var(--muted);font-size:14px}.visual-controls{display:flex;flex:none;gap:8px}.visual-controls button{min-height:40px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--ink);padding:8px 12px;font:inherit;font-weight:700;cursor:pointer}.visual-controls button:first-child{border-color:var(--accent);background:var(--accent);color:#fff}.visual-controls button:focus-visible{outline:3px solid color-mix(in srgb,var(--accent) 28%,transparent);outline-offset:2px}.visual-stage{display:grid;gap:12px}.visual-item{--item-color:var(--accent)}.visual-item.tone-green{--item-color:#15803d}.visual-item.tone-cyan{--item-color:#087f8c}.visual-item.tone-amber{--item-color:#b45309}.visual-item.tone-red{--item-color:#b91c1c}.visual-item.tone-indigo{--item-color:#4338ca}.visual-type-process .visual-stage{grid-template-columns:repeat(auto-fit,minmax(160px,1fr))}.visual-type-process .visual-item,.visual-type-timeline .visual-item{display:flex;align-items:flex-start;gap:12px;border:1px solid var(--line);border-radius:7px;background:#f8fafc;padding:14px}.visual-type-process .visual-item em,.visual-type-timeline .visual-item em{flex:none;width:32px;height:32px;display:grid;place-items:center;border-radius:50%;background:var(--item-color);color:#fff;font-style:normal;font-weight:800}.visual-item>div{min-width:0;display:grid;gap:5px}.visual-item code{justify-self:start;border-radius:4px;background:#e8eef7;padding:3px 6px;color:#1e3a8a;font:700 13px Consolas,monospace}.visual-item small{color:var(--muted);line-height:1.55}.visual-type-timeline .visual-stage{position:relative;padding-left:22px}.visual-type-timeline .visual-stage::before{position:absolute;top:12px;bottom:12px;left:15px;width:2px;background:var(--accent-soft);content:''}.visual-type-timeline .visual-item{position:relative}.visual-type-bars .visual-item{display:grid;grid-template-columns:minmax(100px,.8fr) minmax(160px,2fr) auto;align-items:center;gap:10px}.visual-type-bars .visual-item>div{height:24px;overflow:hidden;border-radius:5px;background:#e8eef7}.visual-type-bars .visual-item i{display:block;width:var(--bar-width);height:100%;border-radius:inherit;background:var(--item-color);transform-origin:left center}.visual-type-bars .visual-item small{grid-column:2/-1}.visual-type-binary .visual-stage{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}.visual-type-binary .visual-item{display:grid;gap:8px;border:1px solid var(--line);border-radius:7px;background:#111827;padding:15px;color:#fff}.binary-code{display:flex;flex-wrap:wrap;gap:4px}.binary-code i{min-width:24px;height:30px;display:grid;place-items:center;border-radius:4px;background:#1e40af;color:#dbeafe;font:700 15px Consolas,monospace;font-style:normal}.visual-type-binary .visual-item small{color:#cbd5e1}.visualization-block.is-running .visual-item{animation:visual-item-enter var(--motion-duration) ease-out both;animation-delay:var(--item-delay)}.visualization-block.is-running.visual-type-bars .visual-item i{animation:visual-bar-grow calc(var(--motion-duration) + 180ms) ease-out both;animation-delay:var(--item-delay)}.visualization-block.is-running.visual-type-binary .binary-code i{animation:visual-digit-pulse 420ms ease-out both;animation-delay:calc(var(--item-delay) + var(--digit-delay))}@keyframes visual-item-enter{from{opacity:.2;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}@keyframes visual-bar-grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}@keyframes visual-digit-pulse{0%{opacity:.25;transform:scale(.82)}70%{background:var(--item-color);color:#fff;transform:scale(1.08)}100%{opacity:1;transform:scale(1)}}
    .visualization-block:not(.is-running) .visual-item{opacity:.28;transform:translateY(12px)}.visualization-block:not(.is-running).visual-type-bars .visual-item i{transform:scaleX(0)}.visualization-block:not(.is-running).visual-type-binary .binary-code i{opacity:.25;transform:scale(.82)}
    .interactive-block>header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:12px}.interactive-block>header button{flex:none;min-height:40px;border:1px solid var(--accent);border-radius:6px;background:#fff;color:var(--accent);padding:8px 13px;font:inherit;font-weight:700;cursor:pointer}.interactive-block>header button:focus-visible{outline:3px solid color-mix(in srgb,var(--accent) 28%,transparent);outline-offset:2px}.interactive-frame{display:block;width:100%;min-height:280px;border:1px solid var(--line);border-radius:7px;background:#fff}#__strata_runtime_error{position:sticky;top:0;z-index:9999;margin:0;padding:10px 12px;border-bottom:1px solid #fecaca;background:#fef2f2;color:#991b1b;font:700 13px/1.5 Inter,'Microsoft YaHei',Arial,sans-serif}
    @media(max-width:640px){main{width:min(100% - 20px,1040px);padding-top:20px}.page-block{padding:16px}.scale-field .choice-grid{grid-template-columns:repeat(3,1fr)}.choice-option{width:100%}.choice-option span{width:100%}.visualization-block>header{display:grid}.visual-controls{width:100%}.visual-controls button{flex:1}.visual-type-process .visual-stage,.visual-type-binary .visual-stage{grid-template-columns:1fr}.visual-type-bars .visual-item{grid-template-columns:1fr auto}.visual-type-bars .visual-item>div{grid-column:1/-1;grid-row:2}.visual-type-bars .visual-item small{grid-column:1/-1}}
  </style>
</head>
<body>
  <main>
    <header class="page-head"><span>STRATA 学习网页 · v${a(v.page.revision_no)}</span><h1>${a(e.title)}</h1>${e.subtitle?`<p>${d(e.subtitle)}</p>`:""}</header>
    ${t}
  </main>
  <script nonce="${h}">
    (() => {
      window.__strataLearningPageBridgeReady = true;
      const source = 'strata-learning-page';
      const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
      const activeBlocks = new Map();
      const reportBlock = block => {
        const state = activeBlocks.get(block);
        if (!state) return;
        activeBlocks.delete(block);
        const visibleMs = Math.min(Math.max(Math.round(performance.now() - state.startedAt), 0), 3600000);
        if (visibleMs < 250) return;
        parent.postMessage({
          source,
          type: 'block-viewed',
          pageId: ${Number(v.page.id)},
          blockId: block.dataset.learningBlockId,
          blockType: block.dataset.learningBlockType,
          visibleMs,
          visibilityRatio: state.maxRatio
        }, '*');
      };
      const blockObserver = new IntersectionObserver(entries => {
        entries.forEach(entry => {
          const block = entry.target;
          if (entry.isIntersecting && entry.intersectionRatio >= 0.5) {
            const state = activeBlocks.get(block);
            if (state) state.maxRatio = Math.max(state.maxRatio, entry.intersectionRatio);
            else activeBlocks.set(block, { startedAt: performance.now(), maxRatio: entry.intersectionRatio });
          } else {
            reportBlock(block);
          }
        });
      }, { threshold: [0, 0.5, 0.75, 1] });
      document.querySelectorAll('[data-learning-block-id]').forEach(block => blockObserver.observe(block));
      addEventListener('pagehide', () => activeBlocks.forEach((_, block) => reportBlock(block)));
      document.querySelectorAll('[data-visualization]').forEach(visualization => {
        let loopTimer = 0;
        const duration = Math.min(Math.max(Number(visualization.dataset.duration || 5000), 1500), 15000);
        const run = () => {
          clearTimeout(loopTimer);
          visualization.classList.remove('is-running');
          void visualization.offsetWidth;
          visualization.classList.add('is-running');
          if (visualization.dataset.loop === 'true' && !reduceMotion) {
            loopTimer = setTimeout(run, duration + 500);
          }
        };
        visualization.querySelector('[data-visual-play]')?.addEventListener('click', run);
        visualization.querySelector('[data-visual-replay]')?.addEventListener('click', run);
        if (visualization.dataset.autoplay === 'true' && !reduceMotion) requestAnimationFrame(run);
      });
      document.querySelectorAll('[data-interactive-reload]').forEach(button => {
        button.addEventListener('click', () => {
          const iframe = button.closest('.interactive-block')?.querySelector('.interactive-frame');
          if (!iframe) return;
          const source = iframe.getAttribute('src')?.split('#strata-reload-')[0];
          if (!source) return;
          iframe.src = 'data:text/html;charset=utf-8,';
          requestAnimationFrame(() => { iframe.src = source; });
        });
      });
      function valueOf(field, form) {
        const id = field.dataset.field;
        const type = field.type;
        if (type === 'radio') return form.querySelector('[data-field="' + CSS.escape(id) + '"]:checked')?.value || '';
        if (type === 'checkbox') return Array.from(form.querySelectorAll('[data-field="' + CSS.escape(id) + '"]:checked')).map(item => item.value);
        if (type === 'number') return field.value === '' ? '' : Number(field.value);
        return field.value;
      }
      function submitForm(form) {
          const answers = {};
          const seen = new Set();
          let valid = true;
          form.querySelectorAll('[data-field]').forEach(field => {
            const id = field.dataset.field;
            if (seen.has(id)) return;
            seen.add(id);
            const value = valueOf(field, form);
            const empty = value === '' || Array.isArray(value) && value.length === 0;
            const wrapper = field.closest('.learning-field');
            wrapper?.classList.toggle('field-invalid', field.dataset.required === 'true' && empty);
            if (field.dataset.required === 'true' && empty) valid = false;
            answers[id] = value;
          });
          const status = form.querySelector('[data-form-status]');
          if (!valid) { if (status) status.textContent = '请完成必填项'; return; }
          const button = form.querySelector('[data-learning-submit]');
          if (button) button.disabled = true;
          if (status) status.textContent = '正在提交...';
          parent.postMessage({ source, type: 'submit', pageId: ${Number(v.page.id)}, formId: form.dataset.learningForm, answers }, '*');
      }
      document.querySelectorAll('form[data-learning-form]').forEach(form => {
        const button = form.querySelector('[data-learning-submit]');
        button?.addEventListener('click', () => submitForm(form));
        form.addEventListener('keydown', event => {
          if (event.key !== 'Enter' || event.shiftKey || event.target?.tagName === 'TEXTAREA') return;
          event.preventDefault();
          button?.click();
        });
      });
      addEventListener('message', event => {
        const data = event.data || {};
        if (data.source !== source || data.type !== 'result') return;
        const form = document.querySelector('form[data-learning-form="' + CSS.escape(data.formId) + '"]');
        if (!form) return;
        const button = form.querySelector('[data-learning-submit]');
        const status = form.querySelector('[data-form-status]');
        if (button) button.disabled = false;
        if (status) { status.textContent = data.message || (data.ok ? '提交成功' : '提交失败'); status.style.color = data.ok ? '#15803d' : '#b91c1c'; }
      });
    })();
  <\/script>
</body>
</html>`});function S(e){if(!x.value||e.source!==x.value.contentWindow)return;const t=e.data;if(!(t?.source!=="strata-learning-page"||Number(t.pageId)!==v.page.id)){if(t.type==="block-viewed"){const i=v.page.schema.blocks.find(n=>n.id===t.blockId&&n.type===t.blockType);if(!i||typeof t.visibleMs!="number"||typeof t.visibilityRatio!="number")return;_("blockViewed",{blockId:i.id,blockType:i.type,visibleMs:Math.min(Math.max(Math.round(t.visibleMs),250),36e5),visibilityRatio:Math.min(Math.max(t.visibilityRatio,0),1)});return}t.type!=="submit"||typeof t.formId!="string"||!t.answers||typeof t.answers!="object"||_("submit",{formId:t.formId,answers:t.answers})}}function I(e,t,i){x.value?.contentWindow?.postMessage({source:"strata-learning-page",type:"result",formId:e,ok:t,message:i},"*")}return N(()=>window.addEventListener("message",S)),H(()=>window.removeEventListener("message",S)),l({notifyResult:I}),(e,t)=>(O(),Y("iframe",{ref_key:"frame",ref:x,class:"learning-page-frame",srcdoc:T.value,title:c.page.title,sandbox:"allow-scripts",referrerpolicy:"no-referrer"},null,8,W))}});export{ee as _,Z as a,V as b,J as c,K as g,U as r,G as s,Q as t};
