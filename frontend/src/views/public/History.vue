<template>
  <div class="page-container">
    <h2 class="page-title">历史咨询</h2>
    <p class="page-sub">查看过往咨询记录，可回放对话并提交满意度反馈</p>

    <el-empty v-if="!store.chatSessions.length" description="暂无历史咨询，去「智能问答」开始提问吧">
      <el-button type="primary" @click="$router.push('/public/chat')">去咨询</el-button>
    </el-empty>

    <el-table v-else :data="store.chatSessions" border>
      <el-table-column prop="title" label="咨询问题" min-width="240" show-overflow-tooltip />
      <el-table-column prop="time" label="时间" width="180" />
      <el-table-column label="消息数" width="90" align="center">
        <template #default="{ row }">{{ row.messages.length }}</template>
      </el-table-column>
      <el-table-column label="满意度" width="160">
        <template #default="{ row }">
          <el-rate v-model="row.satisfaction" disabled />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-button type="primary" text @click="openDrawer(row)">回放</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 回放抽屉 -->
    <el-drawer v-model="drawer" title="对话回放" size="480px">
      <div class="replay">
        <div v-for="(m, i) in current?.messages || []" :key="i" :class="['msg', m.role === 'user' ? 'msg-user' : 'msg-ai']">
          <div class="avatar">{{ m.role === 'user' ? '👤' : '🤖' }}</div>
          <div class="bubble">{{ m.content }}</div>
        </div>
      </div>
      <div class="rate-area">
        <span>满意度评价：</span>
        <el-rate v-model="currentSatisfaction" @change="onRate" />
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useAppStore } from '../../store/app'

const store = useAppStore()
const drawer = ref(false)
const current = ref(null)
const currentSatisfaction = ref(0)

function openDrawer(row) {
  current.value = row
  currentSatisfaction.value = row.satisfaction
  drawer.value = true
}

function onRate(v) {
  if (current.value) {
    store.upsertSession(current.value.id, { ...current.value, satisfaction: v })
    current.value = { ...current.value, satisfaction: v }
    ElMessage.success('反馈已保存')
  }
}
</script>

<style scoped>
.replay {
  padding: 4px;
}
.msg {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
}
.msg-user {
  flex-direction: row-reverse;
}
.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: #eef2fb;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}
.bubble {
  background: #f4f6fb;
  padding: 8px 12px;
  border-radius: 8px;
  line-height: 1.6;
  white-space: pre-wrap;
  max-width: 80%;
}
.msg-user .bubble {
  background: #2f5aa8;
  color: #fff;
}
.rate-area {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 16px;
}
</style>
