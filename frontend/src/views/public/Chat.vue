<template>
  <div class="chat-wrap">
    <div class="chat-head">
      <div>
        <h2 class="page-title" style="margin:0">智能问答</h2>
        <p class="page-sub" style="margin:2px 0 0">AI 助手为您解答事项咨询、材料清单、办理流程与注意事项</p>
      </div>
      <el-button @click="newSession">🆕 新对话</el-button>
    </div>

    <!-- 快捷问题 -->
    <div class="quick-chips">
      <span class="chip-label">快捷提问：</span>
      <el-tag
        v-for="q in quickQuestions"
        :key="q"
        class="chip"
        effect="plain"
        @click="send(q)"
      >{{ q }}</el-tag>
    </div>

    <!-- 消息区 -->
    <div class="msg-list" ref="listRef">
      <el-empty v-if="!messages.length" description="您好，我是政务服务AI助手，请输入您想咨询的事项" />
      <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role === 'user' ? 'msg-user' : 'msg-ai']">
        <div class="avatar">{{ m.role === 'user' ? '👤' : '🤖' }}</div>
        <div class="bubble">
          <div class="bubble-text">{{ m.content }}<span v-if="m.streaming" class="stream-cursor"></span></div>
          <div v-if="m.item" class="bubble-link">
            <el-link type="primary" @click="goItem(m.item.id)">📄 查看【{{ m.item.name }}】材料清单与流程 →</el-link>
          </div>
        </div>
      </div>

      <!-- 满意度 -->
      <div v-if="showRate" class="rate-row">
        <span>本次服务满意吗？</span>
        <el-rate v-model="rate" @change="submitRate" />
      </div>
    </div>

    <!-- 输入区 -->
    <div class="input-bar">
      <el-input
        v-model="input"
        type="textarea"
        :rows="2"
        placeholder="输入您想咨询的政务事项，如：社保转移需要什么材料？"
        resize="none"
        @keydown.enter.exact.prevent="send(input)"
      />
      <div class="input-actions">
        <div class="left">
          <el-button :type="listening ? 'warning' : 'default'" :icon="Microphone" circle @click="toggleVoice" :title="voiceSupported ? '语音输入' : '当前浏览器不支持语音'" />
          <el-button type="danger" plain @click="doHandoff">🧑‍💼 转人工</el-button>
        </div>
        <el-button type="primary" :disabled="!input.trim() || sending" @click="send(input)">发送</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Microphone } from '@element-plus/icons-vue'
import { chatStream, matchItem, handoff } from '../../api'
import { useAppStore } from '../../store/app'

const router = useRouter()
const store = useAppStore()

const input = ref('')
const messages = ref([])
const sending = ref(false)
const listening = ref(false)
const showRate = ref(false)
const rate = ref(0)
const sessionId = ref(null)
const listRef = ref(null)

const quickQuestions = ['社保转移需要什么材料？', '身份证丢了怎么补办？', '营业执照几天能办好？', '公积金租房怎么提取？', '居住证办理需要什么条件？']

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
const voiceSupported = !!SpeechRecognition
let recognition = null

async function scrollBottom() {
  await nextTick()
  if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight
}

function newSession() {
  messages.value = []
  sessionId.value = null
  showRate.value = false
  rate.value = 0
}

async function send(text) {
  const q = (text ?? input.value).trim()
  if (!q || sending.value) return
  input.value = ''
  showRate.value = false
  rate.value = 0

  if (!sessionId.value) sessionId.value = Date.now()
  messages.value.push({ role: 'user', content: q })
  const ai = { role: 'assistant', content: '', streaming: true, item: null }
  messages.value.push(ai)
  sending.value = true
  scrollBottom()

  await chatStream(q, (ch) => { ai.content += ch }, () => { ai.streaming = false })

  // 匹配事项，展示详情链接
  const item = await matchItem(q)
  ai.item = item
  sending.value = false
  showRate.value = true
  scrollBottom()
  saveSession()
}

function saveSession() {
  const msgs = messages.value.filter((m) => m.role && m.content)
  if (!msgs.length) return
  const firstUser = messages.value.find((m) => m.role === 'user')
  store.upsertSession(sessionId.value, {
    id: sessionId.value,
    title: firstUser ? firstUser.content.slice(0, 24) : '咨询',
    time: new Date().toLocaleString('zh-CN'),
    satisfaction: 0,
    messages: messages.value.map((m) => ({ role: m.role, content: m.content }))
  })
}

function goItem(id) {
  router.push(`/public/item/${id}`)
}

async function submitRate(v) {
  const last = messages.value[messages.value.length - 1]
  const firstUser = messages.value.find((m) => m.role === 'user')
  await import('../../api').then(async (api) => {
    await api.addConsultation({
      user: '群众',
      question: firstUser ? firstUser.content : last.content,
      itemId: last.item ? last.item.id : null,
      status: '已答复',
      satisfaction: v,
      time: new Date().toLocaleString('zh-CN'),
      handledBy: 'AI助手'
    })
  })
  // 更新会话满意度
  const s = store.chatSessions.find((x) => x.id === sessionId.value)
  if (s) { s.satisfaction = v; store.upsertSession(sessionId.value, s) }
  ElMessage.success('感谢您的反馈！')
}

async function doHandoff() {
  const q = messages.value.filter((m) => m.role === 'user').map((m) => m.content).pop() || '用户请求转人工'
  await handoff(q)
  ElMessage.success('已为您转接人工客服，请稍候……')
}

function toggleVoice() {
  if (!voiceSupported) {
    ElMessage.warning('当前浏览器不支持语音输入，请使用 Chrome')
    return
  }
  if (listening.value) {
    recognition && recognition.stop()
    listening.value = false
    return
  }
  recognition = new SpeechRecognition()
  recognition.lang = 'zh-CN'
  recognition.interimResults = false
  recognition.onresult = (e) => {
    const text = e.results[0][0].transcript
    input.value = text
    send(text)
  }
  recognition.onend = () => { listening.value = false }
  recognition.onerror = () => { listening.value = false }
  recognition.start()
  listening.value = true
}

onMounted(() => {
  messages.value.push({
    role: 'assistant',
    content: '您好！我是智慧政务AI助手，可以为您解答事项咨询、材料清单、办理流程和注意事项。请直接输入您的问题，或点击上方快捷提问。',
    streaming: false,
    item: null
  })
})
</script>

<style scoped>
.chat-wrap {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 92px);
}
.chat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.quick-chips {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin: 12px 0;
}
.chip-label {
  color: #909399;
  font-size: 13px;
}
.chip {
  cursor: pointer;
}
.msg-list {
  flex: 1;
  overflow-y: auto;
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  border: 1px solid #ebeef5;
}
.msg {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
}
.msg-user {
  flex-direction: row-reverse;
}
.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: #eef2fb;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}
.bubble {
  max-width: 76%;
}
.bubble-text {
  background: #f4f6fb;
  padding: 10px 14px;
  border-radius: 8px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
.msg-user .bubble-text {
  background: #2f5aa8;
  color: #fff;
}
.bubble-link {
  margin-top: 6px;
}
.rate-row {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #606266;
  font-size: 13px;
  padding: 4px 0;
}
.input-bar {
  margin-top: 12px;
}
.input-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
}
.input-actions .left {
  display: flex;
  gap: 8px;
}
</style>
