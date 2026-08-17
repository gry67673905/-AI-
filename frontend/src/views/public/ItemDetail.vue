<template>
  <div class="page-container" v-if="item">
    <el-page-header @back="$router.back()" :content="item.name" />

    <el-card class="card-gap" style="margin-top: 16px">
      <template #header>
        <div class="head">
          <h2 class="page-title" style="margin:0">{{ item.name }}</h2>
          <div>
            <el-tag type="danger" v-if="item.hot">热门</el-tag>
            <el-tag style="margin-left:8px">{{ item.category }}</el-tag>
          </div>
        </div>
      </template>
      <el-descriptions :column="3" border>
        <el-descriptions-item label="事项编码">{{ item.code }}</el-descriptions-item>
        <el-descriptions-item label="办理部门">{{ deptName(item.deptId) }}</el-descriptions-item>
        <el-descriptions-item label="服务对象">{{ item.serviceObject }}</el-descriptions-item>
        <el-descriptions-item label="法律依据">{{ item.legalBasis }}</el-descriptions-item>
        <el-descriptions-item label="办理时限">{{ item.timeLimit }}</el-descriptions-item>
        <el-descriptions-item label="收费标准">{{ item.charge }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card class="card-gap">
      <template #header><b>✅ 办理条件</b></template>
      <el-checkbox-group :model-value="item.conditions.map((_, i) => i)" disabled>
        <el-checkbox v-for="(c, i) in item.conditions" :key="i" :label="i">{{ c }}</el-checkbox>
      </el-checkbox-group>
    </el-card>

    <el-card class="card-gap">
      <template #header><b>📄 材料清单（含预填提示）</b></template>
      <el-table :data="item.materials" border>
        <el-table-column type="index" label="#" width="50" />
        <el-table-column prop="name" label="材料名称" min-width="180" />
        <el-table-column label="必需" width="80">
          <template #default="{ row }">
            <el-tag :type="row.required ? 'danger' : 'info'" size="small">{{ row.required ? '必需' : '可选' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="copies" label="份数" width="140" />
        <el-table-column label="预填提示" min-width="200">
          <template #default="{ row }">
            <el-tooltip :content="row.note || '无'" placement="top">
              <el-tag type="warning" effect="plain" size="small">💡 预填提示</el-tag>
            </el-tooltip>
            <span class="sample">{{ row.sample }}</span>
          </template>
        </el-table-column>
      </el-table>
      <div class="tips">💡 部分材料支持线上预填与样例下载，减少现场填写时间。</div>
    </el-card>

    <el-card class="card-gap">
      <template #header><b>🔄 办理流程</b></template>
      <el-steps :active="item.process.length" direction="vertical" align-center>
        <el-step v-for="(p, i) in item.process" :key="i" :title="p.title" :description="p.desc" />
      </el-steps>
    </el-card>

    <el-card class="card-gap">
      <template #header><b>⚠️ 注意事项</b></template>
      <el-alert :title="item.notice" type="warning" :closable="false" show-icon />
      <div style="margin-top:12px">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="办理窗口">{{ item.window }}</el-descriptions-item>
          <el-descriptions-item label="咨询电话">{{ deptPhone(item.deptId) }}</el-descriptions-item>
        </el-descriptions>
      </div>
    </el-card>

    <div class="actions">
      <el-button type="primary" @click="$router.push('/public/chat')">💬 去咨询</el-button>
      <el-button @click="$router.back()">返回</el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { getItem, deptName } from '../../api'
import { departments } from '../../mock/data'

const route = useRoute()
const item = ref(null)

const deptPhone = (id) => departments.find((d) => d.id === id)?.phone || '—'

onMounted(async () => {
  item.value = await getItem(route.params.id)
})
</script>

<style scoped>
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.sample {
  margin-left: 8px;
  color: #909399;
  font-size: 12px;
}
.tips {
  margin-top: 10px;
  color: #909399;
  font-size: 13px;
}
.actions {
  text-align: center;
  padding: 8px 0 24px;
}
</style>
