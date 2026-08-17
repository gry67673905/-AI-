<template>
  <div class="page-container">
    <h2 class="page-title">群众咨询管理</h2>
    <p class="page-sub">查看群众咨询记录与满意度统计</p>

    <el-row :gutter="16" class="card-gap">
      <el-col :xs="12" :md="6" v-for="s in statCards" :key="s.label">
        <el-card shadow="hover" class="mini-stat">
          <div class="num" :style="{ color: s.color }">{{ s.value }}</div>
          <div class="label">{{ s.label }}</div>
        </el-card>
      </el-col>
    </el-row>

    <div class="toolbar">
      <el-input v-model="kw" placeholder="搜索咨询人/问题" clearable style="width: 280px" prefix-icon="Search" />
      <el-select v-model="statusFilter" placeholder="全部状态" clearable style="width: 140px">
        <el-option label="已答复" value="已答复" />
        <el-option label="转人工" value="转人工" />
        <el-option label="处理中" value="处理中" />
      </el-select>
    </div>

    <el-table :data="filtered" border>
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="user" label="咨询人" width="90" />
      <el-table-column prop="question" label="咨询内容" min-width="240" show-overflow-tooltip />
      <el-table-column label="关联事项" min-width="160">
        <template #default="{ row }">{{ row.itemId ? itemName(row.itemId) : '—' }}</template>
      </el-table-column>
      <el-table-column prop="handledBy" label="处理人" width="120" />
      <el-table-column prop="time" label="时间" width="160" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === '已答复' ? 'success' : row.status === '转人工' ? 'danger' : 'warning'" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="满意度" width="150">
        <template #default="{ row }">
          <el-rate v-model="row.satisfaction" disabled />
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getConsultations, getItems } from '../../api'

const list = ref([])
const kw = ref('')
const statusFilter = ref('')
const itemMap = ref({})

const itemName = (id) => itemMap.value[id] || '—'

const statCards = computed(() => {
  const total = list.value.length
  const answered = list.value.filter((c) => c.status === '已答复').length
  const manual = list.value.filter((c) => c.status === '转人工').length
  const avg = total ? (list.value.reduce((s, c) => s + (c.satisfaction || 0), 0) / total).toFixed(1) : '0'
  return [
    { label: '咨询总量', value: total, color: '#1f3b73' },
    { label: 'AI 已答复', value: answered, color: '#67c23a' },
    { label: '转人工', value: manual, color: '#e6a23c' },
    { label: '平均满意度', value: avg, color: '#f56c6c' }
  ]
})

const filtered = computed(() => {
  return list.value.filter((c) => {
    const hit = !kw.value || c.user.includes(kw.value) || c.question.includes(kw.value)
    const s = !statusFilter.value || c.status === statusFilter.value
    return hit && s
  })
})

onMounted(async () => {
  list.value = await getConsultations()
  const items = await getItems()
  itemMap.value = Object.fromEntries(items.map((i) => [i.id, i.name]))
})
</script>

<style scoped>
.mini-stat {
  text-align: center;
  margin-bottom: 8px;
}
.num {
  font-size: 26px;
  font-weight: 700;
}
.label {
  color: #909399;
  font-size: 13px;
  margin-top: 4px;
}
</style>
