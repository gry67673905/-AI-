<template>
  <div class="page-container">
    <h2 class="page-title">知识辅助</h2>
    <p class="page-sub">检索政务知识库（RAG），快速定位政策条款与关联事项</p>

    <div class="toolbar">
      <el-input
        v-model="kw"
        placeholder="搜索知识库，如：社保、身份证、营业执照、窗口"
        clearable
        style="width: 380px"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="typeFilter" placeholder="全部类型" clearable style="width: 160px">
        <el-option v-for="t in docTypeOptions" :key="t" :label="t" :value="t" />
      </el-select>
    </div>

    <el-table :data="filtered" border>
      <el-table-column prop="title" label="文档标题" min-width="240" show-overflow-tooltip />
      <el-table-column label="类型" width="120">
        <template #default="{ row }">
          <el-tag :type="docType(row.type)" size="small">{{ row.type }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="关联部门" width="180">
        <template #default="{ row }">{{ row.deptId ? deptName(row.deptId) : '通用' }}</template>
      </el-table-column>
      <el-table-column label="关联事项" width="220" show-overflow-tooltip>
        <template #default="{ row }">{{ itemName(row.itemId) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button type="primary" text @click="view(row)">查看</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-drawer v-model="drawer" title="知识文档详情" size="480px">
      <div v-if="current">
        <h3>{{ current.title }}</h3>
        <el-tag :type="docType(current.type)" size="small">{{ current.type }}</el-tag>
        <el-divider />
        <p class="content">{{ current.content }}</p>
        <el-alert title="以上内容为 RAG 检索增强的参考片段，可一键引用到回复" type="info" :closable="false" show-icon />
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getKnowledgeDocs, deptName, getItems } from '../../api'
import { docTypeOptions } from '../../mock/data'

const docs = ref([])
const kw = ref('')
const typeFilter = ref('')
const drawer = ref(false)
const current = ref(null)

const docType = (t) => ({ '办事指南': 'primary', '政策文件': 'warning', '材料模板': 'success', '常见问题': 'info', '窗口信息': 'danger' }[t] || 'info')

const itemMap = ref({})
const itemName = (id) => (id ? (itemMap.value[id] || '—') : '通用')
const filtered = computed(() => {
  return docs.value.filter((d) => {
    const hit = !kw.value || d.title.includes(kw.value) || d.content.includes(kw.value)
    const t = !typeFilter.value || d.type === typeFilter.value
    return hit && t
  })
})

async function view(row) {
  current.value = row
  drawer.value = true
}

onMounted(async () => {
  docs.value = await getKnowledgeDocs()
  const items = await getItems()
  itemMap.value = Object.fromEntries(items.map((i) => [i.id, i.name]))
})
</script>

<style scoped>
.content {
  color: #606266;
  line-height: 1.8;
}
</style>
