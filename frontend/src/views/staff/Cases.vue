<template>
  <div class="page-container">
    <h2 class="page-title">办件处理</h2>
    <p class="page-sub">受理办件、材料审核、条件核验、状态流转，支持办件库自然语言查询（SQL Agent）</p>

    <div class="toolbar">
      <el-input
        v-model="nlQuery"
        placeholder="自然语言查询办件，如：查一下张三的办件 / 所有社保类办件"
        clearable
        style="width: 380px"
        @keyup.enter="runQuery"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button type="primary" @click="runQuery">🔍 SQL Agent 查询</el-button>
      <el-select v-model="statusFilter" placeholder="全部状态" clearable style="width: 140px" @change="load">
        <el-option v-for="s in statusOptions" :key="s" :label="s" :value="s" />
      </el-select>
      <div class="spacer"></div>
      <el-tag type="info">共 {{ list.length }} 件</el-tag>
    </div>

    <el-table :data="list" border>
      <el-table-column prop="id" label="办件号" width="80" />
      <el-table-column prop="itemName" label="事项" min-width="170" show-overflow-tooltip />
      <el-table-column prop="applicant" label="申请人" width="90" />
      <el-table-column prop="idCard" label="证件号" width="150" />
      <el-table-column label="材料" min-width="180">
        <template #default="{ row }">
          <el-tag v-for="m in row.materials" :key="m" size="small" style="margin:2px">{{ m }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="submitTime" label="提交时间" width="160" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200">
        <template #default="{ row }">
          <template v-if="row.status !== '已办结'">
            <el-button type="success" size="small" @click="transit(row, '已办结', '审核通过，已办结')">通过</el-button>
            <el-button type="danger" size="small" @click="transit(row, '已驳回', '材料不全，予以驳回')">驳回</el-button>
          </template>
          <span v-else style="color:#67c23a">已办结</span>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getCases, updateCaseStatus } from '../../api'
import { caseStatusOptions } from '../../mock/data'

const list = ref([])
const all = ref([])
const nlQuery = ref('')
const statusFilter = ref('')
const statusOptions = caseStatusOptions

function statusType(s) {
  return { '待审核': 'warning', '办理中': 'primary', '已办结': 'success', '已驳回': 'danger' }[s] || 'info'
}

async function load() {
  all.value = await getCases()
  applyFilter()
}

function applyFilter() {
  list.value = all.value.filter((c) => !statusFilter.value || c.status === statusFilter.value)
}

// 模拟 SQL Agent：自然语言关键词 → 过滤办件
function runQuery() {
  const q = nlQuery.value.trim()
  if (!q) { ElMessage.warning('请输入查询内容'); return }
  const name = all.value.find((c) => q.includes(c.applicant))
  const kw = q.replace(/查|一下|的|所有|办件|类|怎么样|什么|请|帮我/g, '').trim()
  let result = all.value
  if (name) {
    result = all.value.filter((c) => c.applicant === name.applicant)
  } else if (kw) {
    result = all.value.filter((c) =>
      [c.itemName, c.applicant, c.idCard, c.status].some((f) => f.includes(kw))
    )
  }
  list.value = result
  ElMessage.success(`SQL Agent 检索到 ${result.length} 条办件记录`)
}

async function transit(row, status, result) {
  await updateCaseStatus(row.id, status, result)
  ElMessage.success(`已更新为「${status}」`)
  load()
}

onMounted(load)
</script>
