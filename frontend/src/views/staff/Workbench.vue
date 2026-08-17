<template>
  <div class="page-container">
    <h2 class="page-title">咨询工作台</h2>
    <p class="page-sub">查看群众咨询，接管 AI 转人工会话并回复</p>

    <div class="toolbar">
      <el-radio-group v-model="filter" @change="load">
        <el-radio-button label="全部">全部</el-radio-button>
        <el-radio-button label="转人工">待接管</el-radio-button>
        <el-radio-button label="处理中">处理中</el-radio-button>
        <el-radio-button label="已答复">已答复</el-radio-button>
      </el-radio-group>
    </div>

    <el-table :data="list" border>
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="user" label="咨询人" width="100" />
      <el-table-column prop="question" label="咨询内容" min-width="240" show-overflow-tooltip />
      <el-table-column prop="handledBy" label="处理人" width="120" />
      <el-table-column prop="time" label="时间" width="170" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-button v-if="row.status === '转人工'" type="primary" size="small" @click="take(row)">接管</el-button>
          <el-button v-else-if="row.status === '处理中'" type="success" size="small" @click="reply(row)">回复</el-button>
          <span v-else>—</span>
        </template>
      </el-table-column>
    </el-table>

    <!-- 回复对话框 -->
    <el-dialog v-model="dialog" title="回复群众" width="520px">
      <el-alert :title="`咨询内容：${current?.question}`" type="info" :closable="false" style="margin-bottom:12px" />
      <el-input v-model="replyText" type="textarea" :rows="4" placeholder="输入回复内容，可引用知识库答案" />
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="submitReply">发送回复</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getConsultations, updateConsultation } from '../../api'

const list = ref([])
const filter = ref('全部')
const dialog = ref(false)
const current = ref(null)
const replyText = ref('')

function statusType(s) {
  return { '转人工': 'danger', '处理中': 'warning', '已答复': 'success' }[s] || 'info'
}

async function load() {
  const all = await getConsultations()
  list.value = filter.value === '全部' ? all : all.filter((c) => c.status === filter.value)
}

async function take(row) {
  await updateConsultation(row.id, { status: '处理中', handledBy: '刘芳（窗口1号）' })
  ElMessage.success('已接管该咨询')
  load()
}

function reply(row) {
  current.value = row
  replyText.value = ''
  dialog.value = true
}

async function submitReply() {
  await updateConsultation(current.value.id, { status: '已答复', handledBy: '刘芳（窗口1号）' })
  ElMessage.success('回复已发送')
  dialog.value = false
  load()
}

onMounted(load)
</script>
