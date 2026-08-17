<template>
  <div class="page-container">
    <h2 class="page-title">工作台</h2>
    <p class="page-sub">平台运行概览</p>

    <el-row :gutter="16">
      <el-col v-for="s in stats" :key="s.label" :xs="12" :sm="8" :md="4">
        <el-card class="stat-card card-gap" shadow="hover">
          <div class="stat-icon" :style="{ background: s.color }">{{ s.icon }}</div>
          <div class="stat-num">{{ s.value }}</div>
          <div class="stat-label">{{ s.label }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <el-col :xs="24" :md="12">
        <el-card class="card-gap">
          <template #header><b>📥 最近群众咨询</b></template>
          <el-table :data="consultations.slice(0, 5)" size="small">
            <el-table-column prop="user" label="咨询人" width="80" />
            <el-table-column prop="question" label="问题" show-overflow-tooltip />
            <el-table-column prop="status" label="状态" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="row.status === '已答复' ? 'success' : row.status === '转人工' ? 'danger' : 'warning'">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :xs="24" :md="12">
        <el-card class="card-gap">
          <template #header><b>📋 最近办件</b></template>
          <el-table :data="cases.slice(0, 5)" size="small">
            <el-table-column prop="itemName" label="事项" show-overflow-tooltip />
            <el-table-column prop="applicant" label="申请人" width="80" />
            <el-table-column prop="status" label="状态" width="90">
              <template #default="{ row }">
                <el-tag size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getDepts, getWindows, getStaffs, getItems, getCases, getConsultations } from '../../api'

const depts = ref([])
const windows = ref([])
const staffs = ref([])
const items = ref([])
const cases = ref([])
const consultations = ref([])

const stats = computed(() => [
  { label: '部门', value: depts.value.length, icon: '🏢', color: '#e8f0fe' },
  { label: '窗口', value: windows.value.length, icon: '🪟', color: '#fef3e0' },
  { label: '工作人员', value: staffs.value.length, icon: '👤', color: '#e6f4ea' },
  { label: '政务事项', value: items.value.length, icon: '📄', color: '#fde8e8' },
  { label: '办件记录', value: cases.value.length, icon: '📋', color: '#eef2fb' },
  { label: '群众咨询', value: consultations.value.length, icon: '💬', color: '#f3e8fd' }
])

onMounted(async () => {
  ;[depts.value, windows.value, staffs.value, items.value, cases.value, consultations.value] =
    await Promise.all([getDepts(), getWindows(), getStaffs(), getItems(), getCases(), getConsultations()])
})
</script>

<style scoped>
.stat-card {
  text-align: center;
}
.stat-icon {
  width: 44px;
  height: 44px;
  line-height: 44px;
  border-radius: 10px;
  font-size: 22px;
  margin: 0 auto 8px;
}
.stat-num {
  font-size: 26px;
  font-weight: 700;
  color: #1f3b73;
}
.stat-label {
  color: #909399;
  font-size: 13px;
}
</style>
