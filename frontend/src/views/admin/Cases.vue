<template>
  <div class="page-container">
    <h2 class="page-title">办件记录管理</h2>
    <p class="page-sub">查询办件记录、跟踪办件状态</p>

    <div class="toolbar">
      <el-input v-model="kw" placeholder="搜索申请人/事项/证件号" clearable style="width: 300px" prefix-icon="Search" />
      <el-select v-model="statusFilter" placeholder="全部状态" clearable style="width: 140px">
        <el-option v-for="s in statusOptions" :key="s" :label="s" :value="s" />
      </el-select>
    </div>

    <el-table :data="filtered" border>
      <el-table-column prop="id" label="办件号" width="80" />
      <el-table-column prop="itemName" label="事项" min-width="180" show-overflow-tooltip />
      <el-table-column prop="applicant" label="申请人" width="90" />
      <el-table-column prop="phone" label="联系电话" width="140" />
      <el-table-column label="窗口" width="140">
        <template #default="{ row }">{{ windowName(row.windowId) }}</template>
      </el-table-column>
      <el-table-column prop="submitTime" label="提交时间" width="160" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100">
        <template #default="{ row }">
          <el-button type="primary" text @click="view(row)">详情</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-drawer v-model="drawer" title="办件详情" size="460px">
      <el-descriptions v-if="current" :column="1" border>
        <el-descriptions-item label="办件号">{{ current.id }}</el-descriptions-item>
        <el-descriptions-item label="事项">{{ current.itemName }}</el-descriptions-item>
        <el-descriptions-item label="申请人">{{ current.applicant }}</el-descriptions-item>
        <el-descriptions-item label="证件号">{{ current.idCard }}</el-descriptions-item>
        <el-descriptions-item label="联系电话">{{ current.phone }}</el-descriptions-item>
        <el-descriptions-item label="提交时间">{{ current.submitTime }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ current.status }}</el-descriptions-item>
        <el-descriptions-item label="办理结果">{{ current.result || '—' }}</el-descriptions-item>
      </el-descriptions>
      <el-divider />
      <b>申报材料：</b>
      <div style="margin-top:8px">
        <el-tag v-for="m in current?.materials" :key="m" style="margin:4px">{{ m }}</el-tag>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getCases, windowName } from '../../api'
import { caseStatusOptions } from '../../mock/data'

const list = ref([])
const kw = ref('')
const statusFilter = ref('')
const drawer = ref(false)
const current = ref(null)
const statusOptions = caseStatusOptions

function statusType(s) {
  return { '待审核': 'warning', '办理中': 'primary', '已办结': 'success', '已驳回': 'danger' }[s] || 'info'
}

const filtered = computed(() => {
  return list.value.filter((c) => {
    const hit = !kw.value || [c.applicant, c.itemName, c.idCard, c.phone].some((f) => f.includes(kw.value))
    const s = !statusFilter.value || c.status === statusFilter.value
    return hit && s
  })
})

function view(row) {
  current.value = row
  drawer.value = true
}

onMounted(async () => {
  list.value = await getCases()
})
</script>
