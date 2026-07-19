<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { LearningPage, LearningPageBlock, LearningPageField, LearningPageVisualizationItem } from '@/api/learningPages'

const props = withDefaults(defineProps<{
  page: LearningPage
  interactive?: boolean
}>(), {
  interactive: false
})

const emit = defineEmits<{
  submit: [payload: { formId: string; answers: Record<string, unknown> }]
  blockViewed: [payload: { blockId: string; blockType: LearningPageBlock['type']; visibleMs: number; visibilityRatio: number }]
}>()

const frame = ref<HTMLIFrameElement | null>(null)
const scriptNonce = 'c3RyYXRhLWxlYXJuaW5nLXBhZ2U='

function escapeHtml(value: unknown) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
}

function textHtml(value: unknown) {
  return escapeHtml(value).replaceAll('\n', '<br>')
}

function utf8Base64(value: string) {
  const bytes = new TextEncoder().encode(value)
  let binary = ''
  const chunkSize = 0x8000
  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize))
  }
  return btoa(binary)
}

function fieldHtml(field: LearningPageField, formId: string) {
  const fieldId = escapeHtml(field.id)
  const name = escapeHtml(`${formId}:${field.id}`)
  const required = field.required ? ' data-required="true"' : ''
  const disabled = props.interactive ? '' : ' disabled'
  const placeholder = escapeHtml(field.placeholder || '')
  const label = `<span class="field-label">${escapeHtml(field.label)}${field.required ? '<b>*</b>' : ''}</span>`
  if (field.type === 'single' || field.type === 'scale') {
    const options = (field.options || []).map((option, index) => `
      <label class="choice-option">
        <input data-field="${fieldId}"${required} type="radio" name="${name}" value="${escapeHtml(option)}"${disabled}>
        <span>${field.type === 'scale' ? `<strong>${index + 1}</strong>` : ''}${escapeHtml(option)}</span>
      </label>`).join('')
    return `<fieldset class="learning-field ${field.type === 'scale' ? 'scale-field' : ''}"><legend>${label}</legend><div class="choice-grid">${options}</div></fieldset>`
  }
  if (field.type === 'multiple') {
    const options = (field.options || []).map((option) => `
      <label class="choice-option">
        <input data-field="${fieldId}"${required} type="checkbox" name="${name}" value="${escapeHtml(option)}"${disabled}>
        <span>${escapeHtml(option)}</span>
      </label>`).join('')
    return `<fieldset class="learning-field"><legend>${label}</legend><div class="choice-grid">${options}</div></fieldset>`
  }
  if (field.type === 'select') {
    const options = (field.options || []).map((option) => `<option value="${escapeHtml(option)}">${escapeHtml(option)}</option>`).join('')
    return `<label class="learning-field">${label}<select data-field="${fieldId}"${required}${disabled}><option value="">请选择</option>${options}</select></label>`
  }
  if (field.type === 'long_text') {
    return `<label class="learning-field">${label}<textarea data-field="${fieldId}"${required} maxlength="8000" rows="5" placeholder="${placeholder}"${disabled}></textarea></label>`
  }
  if (field.type === 'number') {
    const min = field.min === null || field.min === undefined ? '' : ` min="${escapeHtml(field.min)}"`
    const max = field.max === null || field.max === undefined ? '' : ` max="${escapeHtml(field.max)}"`
    return `<label class="learning-field">${label}<input data-field="${fieldId}"${required} type="number"${min}${max} placeholder="${placeholder}"${disabled}></label>`
  }
  return `<label class="learning-field">${label}<input data-field="${fieldId}"${required} type="text" maxlength="1000" placeholder="${placeholder}"${disabled}></label>`
}

function visualizationHtml(block: LearningPageBlock) {
  const visualizationType = ['process', 'timeline', 'bars', 'binary'].includes(block.visualization_type || '')
    ? block.visualization_type!
    : 'process'
  const items = (block.items || []).filter((item): item is LearningPageVisualizationItem => (
    typeof item === 'object' && 'label' in item && 'detail' in item
  ))
  if (items.length < 2) return ''
  const duration = Math.min(Math.max(Number(block.duration_ms || 5000), 1500), 15000)
  const itemDelay = Math.max(Math.floor(duration / items.length), 120)
  const motionDuration = Math.min(Math.max(Math.floor(itemDelay * 0.72), 280), 850)
  const values = items.map((item) => Number(item.value || 0))
  const maxValue = Math.max(...values, 1)
  const description = block.description ? `<p class="visual-description">${textHtml(block.description)}</p>` : ''
  const itemHtml = items.map((item, index) => {
    const tone = ['blue', 'green', 'cyan', 'amber', 'red', 'indigo'].includes(item.tone) ? item.tone : 'blue'
    const style = `--item-delay:${index * itemDelay}ms;--motion-duration:${motionDuration}ms`
    if (visualizationType === 'bars') {
      const value = Number(item.value || 0)
      const width = Math.min(Math.max(value * 100 / maxValue, 0), 100)
      return `<article class="visual-item tone-${tone}" style="${style};--bar-width:${width}%"><span>${escapeHtml(item.label)}</span><div><i></i></div><strong>${escapeHtml(value)}</strong>${item.detail ? `<small>${textHtml(item.detail)}</small>` : ''}</article>`
    }
    if (visualizationType === 'binary') {
      const code = String(item.code || item.value || '')
      const digits = [...code].slice(0, 32).map((digit, digitIndex) => `<i style="--digit-delay:${digitIndex * 45}ms">${escapeHtml(digit)}</i>`).join('')
      return `<article class="visual-item tone-${tone}" style="${style}"><span>${escapeHtml(item.label)}</span><strong class="binary-code">${digits || '<i>-</i>'}</strong>${item.detail ? `<small>${textHtml(item.detail)}</small>` : ''}</article>`
    }
    return `<article class="visual-item tone-${tone}" style="${style}"><em>${index + 1}</em><div><strong>${escapeHtml(item.label)}</strong>${item.code ? `<code>${escapeHtml(item.code)}</code>` : ''}${item.detail ? `<small>${textHtml(item.detail)}</small>` : ''}</div></article>`
  }).join('')
  return `<section class="page-block visualization-block visual-type-${visualizationType}" data-visualization data-duration="${duration}" data-autoplay="${block.autoplay !== false}" data-loop="${Boolean(block.loop)}"><header><div>${block.title ? `<h2>${escapeHtml(block.title)}</h2>` : ''}${description}</div><div class="visual-controls"><button type="button" data-visual-play>播放动画</button><button type="button" data-visual-replay>重新播放</button></div></header><div class="visual-stage">${itemHtml}</div></section>`
}

function interactiveHtml(block: LearningPageBlock) {
  const height = Math.min(Math.max(Number(block.height || 520), 280), 900)
  const css = String(block.css || '').replace(/<\/style/gi, '<\\/style')
  const javascript = String(block.javascript || '').replace(/<\/script/gi, '<\\/script')
  const innerDocument = `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${scriptNonce}'; img-src data: blob:; media-src data: blob:; connect-src 'none'; frame-src 'none'; object-src 'none'; form-action 'none'; base-uri 'none'">
  <style>*{box-sizing:border-box}html,body{margin:0;min-height:100%;font-family:Inter,'Microsoft YaHei',Arial,sans-serif;color:#172033;background:#fff}button,input,select,textarea{font:inherit}${css}</style>
</head>
<body>
<div id="__strata_runtime_error" role="alert" hidden></div>
${String(block.html || '')}
<script nonce="${scriptNonce}">
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
<script nonce="${scriptNonce}">${javascript}<\/script>
</body>
</html>`
  const source = `data:text/html;charset=utf-8;base64,${utf8Base64(innerDocument)}`
  const description = block.description ? `<p class="visual-description">${textHtml(block.description)}</p>` : ''
  return `<section class="page-block interactive-block"><header><div>${block.title ? `<h2>${escapeHtml(block.title)}</h2>` : ''}${description}</div><button type="button" data-interactive-reload>重新运行</button></header><iframe class="interactive-frame" title="${escapeHtml(block.title || '交互动画')}" sandbox="allow-scripts" referrerpolicy="no-referrer" loading="lazy" style="height:${height}px" src="${escapeHtml(source)}"></iframe></section>`
}

function trackedBlockHtml(html: string, block: LearningPageBlock, index: number) {
  const blockId = escapeHtml(block.id || `block_${index + 1}`)
  const blockType = escapeHtml(block.type)
  return html.replace(
    '<section ',
    `<section data-learning-block-id="${blockId}" data-learning-block-type="${blockType}" `
  )
}

function blockHtml(block: LearningPageBlock, index: number) {
  const title = block.title ? `<h2>${escapeHtml(block.title)}</h2>` : ''
  if (block.type === 'content') {
    return trackedBlockHtml(`<section class="page-block content-block">${title}<p>${textHtml(block.body)}</p></section>`, block, index)
  }
  if (block.type === 'callout') {
    return trackedBlockHtml(`<section class="page-block callout-block tone-${escapeHtml(block.tone || 'info')}">${title}<p>${textHtml(block.body)}</p></section>`, block, index)
  }
  if (block.type === 'list') {
    const items = (block.items || []).filter((item): item is string => typeof item === 'string').map((item) => `<li>${textHtml(item)}</li>`).join('')
    return trackedBlockHtml(`<section class="page-block list-block">${title}<ul>${items}</ul></section>`, block, index)
  }
  if (block.type === 'steps' || block.type === 'cards') {
    const items = (block.items || []).filter((item): item is { title: string; body: string } => typeof item === 'object').map((item, itemIndex) => `
      <article><em>${block.type === 'steps' ? itemIndex + 1 : ''}</em><div><h3>${escapeHtml(item.title)}</h3><p>${textHtml(item.body)}</p></div></article>`).join('')
    return trackedBlockHtml(`<section class="page-block ${block.type}-block">${title}<div class="${block.type}-grid">${items}</div></section>`, block, index)
  }
  if (block.type === 'table') {
    const headers = (block.headers || []).map((item) => `<th>${escapeHtml(item)}</th>`).join('')
    const rows = (block.rows || []).map((row) => `<tr>${row.map((item) => `<td>${textHtml(item)}</td>`).join('')}</tr>`).join('')
    return trackedBlockHtml(`<section class="page-block table-block">${title}<div class="table-wrap"><table><thead><tr>${headers}</tr></thead><tbody>${rows}</tbody></table></div></section>`, block, index)
  }
  if (block.type === 'code') {
    return trackedBlockHtml(`<section class="page-block code-block">${title}<span>${escapeHtml(block.language || 'text')}</span><pre><code>${escapeHtml(block.code || '')}</code></pre></section>`, block, index)
  }
  if (block.type === 'visualization') {
    return trackedBlockHtml(visualizationHtml(block), block, index)
  }
  if (block.type === 'interactive') {
    return trackedBlockHtml(interactiveHtml(block), block, index)
  }
  if (block.type === 'form') {
    const formId = escapeHtml(block.form_id || `form_${index + 1}`)
    const fields = (block.fields || []).map((field) => fieldHtml(field, block.form_id || `form_${index + 1}`)).join('')
    const description = block.description ? `<p class="form-description">${textHtml(block.description)}</p>` : ''
    const submit = props.interactive
      ? `<button type="button" data-learning-submit="${formId}">${escapeHtml(block.submit_label || '提交')}</button>`
      : '<button type="button" disabled>教师预览</button>'
    return trackedBlockHtml(`<section class="page-block form-block">${title}${description}<form data-learning-form="${formId}" novalidate>${fields}<footer>${submit}<span data-form-status="${formId}"></span></footer></form></section>`, block, index)
  }
  return ''
}

const srcdoc = computed(() => {
  const schema = props.page.schema
  const blocks = (schema.blocks || []).map(blockHtml).join('')
  const accent = escapeHtml(schema.accent || 'blue')
  return `<!doctype html>
<html lang="zh-CN" data-accent="${accent}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${scriptNonce}'; img-src data:; connect-src 'none'; media-src 'none'; font-src 'none'; frame-src data:; object-src 'none'; form-action 'none'; base-uri 'none'">
  <title>${escapeHtml(schema.title)}</title>
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
    <header class="page-head"><span>STRATA 学习网页 · v${escapeHtml(props.page.revision_no)}</span><h1>${escapeHtml(schema.title)}</h1>${schema.subtitle ? `<p>${textHtml(schema.subtitle)}</p>` : ''}</header>
    ${blocks}
  </main>
  <script nonce="${scriptNonce}">
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
          pageId: ${Number(props.page.id)},
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
          parent.postMessage({ source, type: 'submit', pageId: ${Number(props.page.id)}, formId: form.dataset.learningForm, answers }, '*');
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
</html>`
})

function onMessage(event: MessageEvent) {
  if (!frame.value || event.source !== frame.value.contentWindow) return
  const data = event.data as Record<string, unknown>
  if (data?.source !== 'strata-learning-page' || Number(data.pageId) !== props.page.id) return
  if (data.type === 'block-viewed') {
    const block = props.page.schema.blocks.find((item) => item.id === data.blockId && item.type === data.blockType)
    if (!block || typeof data.visibleMs !== 'number' || typeof data.visibilityRatio !== 'number') return
    emit('blockViewed', {
      blockId: block.id,
      blockType: block.type,
      visibleMs: Math.min(Math.max(Math.round(data.visibleMs), 250), 3_600_000),
      visibilityRatio: Math.min(Math.max(data.visibilityRatio, 0), 1)
    })
    return
  }
  if (data.type !== 'submit' || typeof data.formId !== 'string' || !data.answers || typeof data.answers !== 'object') return
  emit('submit', { formId: data.formId, answers: data.answers as Record<string, unknown> })
}

function notifyResult(formId: string, ok: boolean, message: string) {
  frame.value?.contentWindow?.postMessage({
    source: 'strata-learning-page',
    type: 'result',
    formId,
    ok,
    message
  }, '*')
}

onMounted(() => window.addEventListener('message', onMessage))
onBeforeUnmount(() => window.removeEventListener('message', onMessage))

defineExpose({ notifyResult })
</script>

<template>
  <iframe
    ref="frame"
    class="learning-page-frame"
    :srcdoc="srcdoc"
    :title="page.title"
    sandbox="allow-scripts"
    referrerpolicy="no-referrer"
  ></iframe>
</template>
