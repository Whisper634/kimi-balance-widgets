/**
 * 卡片渲染自测：不联网、不开浏览器。
 *
 * 做法：把每个 index.html 里的 <script> 抠出来，在一个最小的 DOM/窗口桩里跑，
 * 先渲染 SAMPLE（模拟"没有绑定数据"），再通过 onDataChange 喂一份带派生字段的真实结构，
 * 断言两件事：① 不抛异常 ② 新加的决策行确实渲染出了内容。
 *
 * 用法： node tools/html_render_test.mjs
 */
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'

const ROOT = path.dirname(new URL(import.meta.url).pathname)
const REPO = path.resolve(ROOT, '..')

let fails = 0
function ok(name, cond, extra) {
  console.log(`  ${cond ? 'ok  ' : 'FAIL'} ${name}${cond || !extra ? '' : ' :: ' + extra}`)
  if (!cond) fails++
}

function fakeEl() {
  return {
    innerHTML: '', textContent: '', className: '', style: {}, children: [],
    addEventListener() {}, removeEventListener() {}, closest() { return null },
    querySelectorAll() { return [] }, setAttribute() {}, getAttribute() { return null },
  }
}

function runCard(rel, fixture) {
  const html = fs.readFileSync(path.join(REPO, rel), 'utf8')
  const m = html.match(/<script>([\s\S]*?)<\/script>/)
  if (!m) throw new Error('没找到 <script>: ' + rel)

  const els = {}
  const doc = {
    getElementById(id) {
      if (!els[id]) els[id] = fakeEl()
      return els[id]
    },
    querySelectorAll() { return [] },
    addEventListener() {},
  }
  const storage = { getItem() { return null }, setItem() {} }
  const feed = { main: fixture }
  const win = {
    DaimonWidget: {
      data: { main: fixture },
      onDataChange(cb) { cb(feed) },   // 第二遍渲染走派生字段
    },
  }
  const ctx = vm.createContext({ document: doc, window: win, console, Date, Math, Number, String, isNaN, localStorage: storage })
  vm.runInContext(m[1], ctx, { filename: rel })
  return els
}

console.log('[卡片 1] DeepSeek 余额')
let els = runCard('widgets/deepseek-balance/index.html', {
  ok: true, available: true, currency: 'CNY', total: 96.5, granted: 0, toppedUp: 96.5,
  series: [{ date: '10-28', used: 1.2 }, { date: '10-29', used: 0 }],
  level: 'ok', burnPerDay: 0.21, daysLeft: 459.5, exhaustAt: '2028-01-03T00:00:00+00:00',
  windowDays: 7, samples: 12, hint: '日均 ¥0.21',
})
ok('余额渲染出来了', els.body.innerHTML.includes('96.50'))
ok('决策行有日均与天数', els.insight.innerHTML.includes('日均') && els.insight.innerHTML.includes('天'))
ok('决策行按级别带 class', els.insight.innerHTML.includes('insight ok'))
ok('折线图渲染出来了', els.chart.innerHTML.includes('<svg') && els.chart.innerHTML.includes('10-28'))
ok('大字号已生效', fs.readFileSync(path.join(REPO, 'widgets/deepseek-balance/index.html'), 'utf8').includes('font-size: 56px'))

console.log('[卡片 2] Kimi API 余额（告急态）')
els = runCard('widgets/kimi-api-balance/index.html', {
  ok: true, available: true, currency: 'CNY', total: 60.94, cash: 47.97, voucher: 12.97,
  cashPct: 78.7, voucherPct: 21.3,
  series: [{ date: '10-28', used: 0.8 }, { date: '10-29', used: 2.4 }],
  level: 'alert', burnPerDay: 3.2, daysLeft: 19, exhaustAt: '2026-11-10T00:00:00+00:00',
  windowDays: 7, samples: 9, hint: '余额告急',
})
ok('总额渲染出来了', els.body.innerHTML.includes('60.94'))
ok('告急态渲染 ⚠️', els.insight.innerHTML.includes('⚠️'))
ok('告急态 class 正确', els.insight.innerHTML.includes('insight alert'))
ok('Kimi API 卡也有折线图', els.chart.innerHTML.includes('<svg'))

console.log('[卡片 3] Kimi 订阅用量（活不过重置）')
els = runCard('widgets/kimi-subscription-usage/index.html', {
  ok: true, active: true, plan: 'Allegretto', totalPct: 42.5, remainingPct: 57.5, codePct: 0,
  resetAt: '2026-11-17T09:10:55Z', subEnd: '2027-07-18T00:00:00Z',
  boostLeft: 0, boostTotal: 175, boostMonthlyUsed: 0,
  series: [{ date: '10-28', used: 3.1 }, { date: '10-29', used: 6.0 }],
  level: 'alert', burnPerDay: 8.5, daysLeft: 4.9, daysToReset: 26,
  exhaustAt: '2026-10-29T00:00:00+00:00', windowDays: 7, samples: 30, hint: '撑不到重置',
})
ok('用量渲染出来了', els.body.innerHTML.includes('42.5%'))
ok('决策行给出撑不到重置', els.insight.innerHTML.includes('撑不到重置'))
ok('决策行有距重置天数', els.insight.innerHTML.includes('距重置 26'))
ok('订阅卡折线图按"个点"渲染', els.chart.innerHTML.includes('个点'))

console.log('[卡片 4] 火山免费额度（价值排序）')
els = runCard('widgets/volc-engine-quota/index.html', {
  ok: true, accountId: 2133281834, updatedAt: 'req',
  totalValueOut: 22.71, totalValueIn: 4.0, remainAll: 1490496, tokensAll: 1500000,
  level: 'ok', burnPerDay: 2281, daysLeft: 653, exhaustAt: '2028-08-01T00:00:00+00:00',
  windowDays: 7, samples: 5, priorityName: 'GLM-5.2',
  hint: '合计剩余价值约 ¥22.71（按输出价） · 先用 GLM-5.2（值 ¥14.00）',
  models: [
    { name: 'glm-5-2', display: 'GLM-5.2', vendor: '智谱AI', opened: true, total: 500000, consumed: 0, remaining: 500000, remainingPct: 100, priceIn: 0.008, priceOut: 0.028, valueOut: 14, valueIn: 4, priority: 1 },
    { name: 'doubao-seed-2-1-turbo', display: 'Doubao-Seed-2.1-turbo', vendor: '字节跳动', opened: true, total: 500000, consumed: 9504, remaining: 490496, remainingPct: 98.1, priceIn: 0.003, priceOut: 0.015, valueOut: 7.36, valueIn: 1.47, priority: 2 },
  ],
})
ok('模型行渲染出来了', els.list.innerHTML.includes('GLM-5.2'))
ok('合计价值出现在摘要', els.summary.textContent.includes('22.71'))
ok('先烧谁有徽标', els.list.innerHTML.includes('先用'))
ok('每行有折算价值', els.list.innerHTML.includes('值 ¥14.00'))
ok('决策行用了后端 hint', els.insight.innerHTML.includes('先用 GLM-5.2'))

console.log('')
if (fails) {
  console.log(`失败 ${fails} 项`)
  process.exit(1)
}
console.log('全部通过')
