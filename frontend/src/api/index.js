// 模拟 API 层：数据结构与真实 REST 接口一致，后续可无缝替换为 axios 调用。
// 所有写操作作用于 reactive 的 db，页面可实时看到增删改查结果。
import { reactive } from 'vue'
import * as raw from '../mock/data'

const delay = (ms = 200) => new Promise((r) => setTimeout(r, ms))

const db = reactive({
  departments: [...raw.departments],
  windows: [...raw.windows],
  staffs: [...raw.staffs],
  items: [...raw.items],
  cases: [...raw.cases],
  consultations: [...raw.consultations],
  knowledgeDocs: [...raw.knowledgeDocs],
  faq: [...raw.faq]
})

const nextId = (list) => (list.length ? Math.max(...list.map((x) => x.id)) + 1 : 1)

// ---------- 字典辅助 ----------
export const deptName = (id) => db.departments.find((d) => d.id === id)?.name || '—'
export const windowName = (id) => db.windows.find((w) => w.id === id)?.name || '—'
export const staffName = (id) => db.staffs.find((s) => s.id === id)?.name || '—'

// ---------- 事项 ----------
export async function getItems() {
  await delay()
  return db.items
}
export async function getItem(id) {
  await delay()
  return db.items.find((i) => i.id === Number(id))
}
export async function searchItems(keyword = '', category = '') {
  await delay()
  return db.items.filter((i) => {
    const kw = keyword.toLowerCase()
    const hit = !kw || i.name.toLowerCase().includes(kw) || i.code.toLowerCase().includes(kw)
    const cat = !category || i.category === category
    return hit && cat
  })
}
export async function saveItem(item) {
  await delay()
  if (item.id) {
    const idx = db.items.findIndex((i) => i.id === item.id)
    if (idx > -1) db.items[idx] = { ...db.items[idx], ...item }
    return db.items[idx]
  }
  const n = { ...item, id: nextId(db.items) }
  db.items.unshift(n)
  return n
}
export async function deleteItem(id) {
  await delay()
  const idx = db.items.findIndex((i) => i.id === id)
  if (idx > -1) db.items.splice(idx, 1)
}

// ---------- 部门 ----------
export async function getDepts() { await delay(); return db.departments }
export async function saveDept(dept) {
  await delay()
  if (dept.id) {
    const idx = db.departments.findIndex((d) => d.id === dept.id)
    if (idx > -1) db.departments[idx] = { ...db.departments[idx], ...dept }
    return db.departments[idx]
  }
  const n = { ...dept, id: nextId(db.departments) }
  db.departments.push(n)
  return n
}
export async function deleteDept(id) {
  await delay()
  const idx = db.departments.findIndex((d) => d.id === id)
  if (idx > -1) db.departments.splice(idx, 1)
}

// ---------- 窗口 ----------
export async function getWindows() { await delay(); return db.windows }
export async function saveWindow(win) {
  await delay()
  if (win.id) {
    const idx = db.windows.findIndex((w) => w.id === win.id)
    if (idx > -1) db.windows[idx] = { ...db.windows[idx], ...win }
    return db.windows[idx]
  }
  const n = { ...win, id: nextId(db.windows) }
  db.windows.push(n)
  return n
}
export async function deleteWindow(id) {
  await delay()
  const idx = db.windows.findIndex((w) => w.id === id)
  if (idx > -1) db.windows.splice(idx, 1)
}

// ---------- 工作人员 ----------
export async function getStaffs() { await delay(); return db.staffs }
export async function saveStaff(staff) {
  await delay()
  if (staff.id) {
    const idx = db.staffs.findIndex((s) => s.id === staff.id)
    if (idx > -1) db.staffs[idx] = { ...db.staffs[idx], ...staff }
    return db.staffs[idx]
  }
  const n = { ...staff, id: nextId(db.staffs) }
  db.staffs.push(n)
  return n
}
export async function deleteStaff(id) {
  await delay()
  const idx = db.staffs.findIndex((s) => s.id === id)
  if (idx > -1) db.staffs.splice(idx, 1)
}

// ---------- 办件 ----------
export async function getCases() { await delay(); return db.cases }
export async function updateCaseStatus(id, status, result = '') {
  await delay()
  const c = db.cases.find((x) => x.id === id)
  if (c) { c.status = status; c.result = result }
  return c
}

// ---------- 咨询 ----------
export async function getConsultations() { await delay(); return db.consultations }
export async function addConsultation(consult) {
  await delay(50)
  const n = { id: nextId(db.consultations), satisfaction: 0, ...consult }
  db.consultations.unshift(n)
  return n
}
export async function updateConsultation(id, patch) {
  const c = db.consultations.find((x) => x.id === id)
  if (c) Object.assign(c, patch)
  return c
}

// ---------- 知识库 ----------
export async function getKnowledgeDocs() { await delay(); return db.knowledgeDocs }
export async function addKnowledgeDoc(doc) {
  await delay()
  const n = { id: nextId(db.knowledgeDocs), ...doc }
  db.knowledgeDocs.unshift(n)
  return n
}
export async function deleteKnowledgeDoc(id) {
  await delay()
  const idx = db.knowledgeDocs.findIndex((d) => d.id === id)
  if (idx > -1) db.knowledgeDocs.splice(idx, 1)
}

// ---------- 智能问答 ----------
function findItemByKeyword(query) {
  for (const f of db.faq) {
    if (query.includes(f.q) || f.q.includes(query)) return db.items.find((i) => i.id === f.itemId)
  }
  const hot = db.items.find((i) => i.hot && query.includes(i.name.slice(0, 2)))
  return hot || null
}

function buildAnswer(query) {
  const item = findItemByKeyword(query)
  if (item) {
    const mats = item.materials.map((m) => `· ${m.name}（${m.copies}，${m.required ? '必需' : '可选'}）`).join('\n')
    const steps = item.process.map((p, i) => `${i + 1}. ${p.title}：${p.desc}`).join('\n')
    return (
      `已为您匹配到事项【${item.name}】（编码 ${item.code}，${deptName(item.deptId)}）。\n\n` +
      `【办理条件】\n${item.conditions.map((c) => '· ' + c).join('\n')}\n\n` +
      `【材料清单】\n${mats}\n\n` +
      `【办理流程】\n${steps}\n\n` +
      `【注意事项】\n${item.notice}\n\n` +
      `办理时限：${item.timeLimit}；收费：${item.charge}；办理窗口：${item.window}。`
    )
  }
  return (
    '抱歉，暂未精准匹配到具体事项。您可以尝试：\n' +
    '· 输入事项关键词，如“社保转移”“身份证”“营业执照”“公积金”等；\n' +
    '· 或点击右上角“转人工”，由工作人员为您解答。'
  )
}

// 流式回答：逐字回调 onToken，结束回调 onDone
export async function chatStream(query, onToken, onDone) {
  const answer = buildAnswer(query)
  for (const ch of answer) {
    onToken(ch)
    await delay(12)
  }
  onDone && onDone(answer)
  return answer
}

// 非流式回答
export async function chat(query) {
  await delay(300)
  return buildAnswer(query)
}

// 匹配事项（供“查看详情/材料清单”跳转使用）
export async function matchItem(query) {
  await delay(50)
  return findItemByKeyword(query)
}

// 转人工：生成咨询记录并标记为转人工
export async function handoff(query, user = '群众') {
  const n = {
    id: nextId(db.consultations),
    user,
    question: query,
    itemId: null,
    status: '转人工',
    satisfaction: 0,
    time: new Date().toLocaleString('zh-CN'),
    handledBy: '待分配'
  }
  db.consultations.unshift(n)
  return n
}
