<template>
  <div class="page-container">
    <h2 class="page-title">事项搜索</h2>
    <p class="page-sub">按关键词或分类查找政务事项，查看办理条件、材料清单与流程</p>

    <div class="toolbar">
      <el-input
        v-model="keyword"
        placeholder="输入事项名称或关键词，如：社保、身份证、营业执照"
        clearable
        style="width: 420px"
        @keyup.enter="doSearch"
        @clear="doSearch"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="category" placeholder="全部分类" clearable style="width: 180px" @change="doSearch">
        <el-option v-for="c in categoryOptions" :key="c" :label="c" :value="c" />
      </el-select>
      <el-button type="primary" @click="doSearch"><el-icon><Search /></el-icon>搜索</el-button>
      <div class="spacer"></div>
      <el-tag type="info">共 {{ list.length }} 项</el-tag>
    </div>

    <el-row :gutter="16">
      <el-col v-for="item in list" :key="item.id" :xs="24" :sm="12" :md="8">
        <el-card class="item-card card-gap" shadow="hover" @click="goDetail(item.id)">
          <div class="item-head">
            <span class="item-name">{{ item.name }}</span>
            <el-tag v-if="item.hot" type="danger" size="small">热门</el-tag>
          </div>
          <div class="item-meta">
            <el-tag size="small" type="primary">{{ item.category }}</el-tag>
            <span class="code">{{ item.code }}</span>
          </div>
          <div class="item-desc">
            <div>办理部门：{{ deptName(item.deptId) }}</div>
            <div>办理时限：{{ item.timeLimit }} · {{ item.charge }}</div>
          </div>
          <div class="item-foot">
            <el-button type="primary" text size="small" @click.stop="goDetail(item.id)">
              查看详情 <el-icon><ArrowRight /></el-icon>
            </el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-empty v-if="!list.length" description="未找到相关事项" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { searchItems, deptName, getItems } from '../../api'
import { categoryOptions } from '../../mock/data'

const router = useRouter()
const keyword = ref('')
const category = ref('')
const list = ref([])

async function doSearch() {
  list.value = await searchItems(keyword.value, category.value)
}

function goDetail(id) {
  router.push(`/public/item/${id}`)
}

onMounted(async () => {
  list.value = await getItems()
})
</script>

<style scoped>
.item-card {
  cursor: pointer;
}
.item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.item-name {
  font-size: 16px;
  font-weight: 600;
  color: #1f3b73;
}
.item-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 10px 0;
}
.code {
  color: #909399;
  font-size: 12px;
}
.item-desc {
  color: #606266;
  font-size: 13px;
  line-height: 1.8;
}
.item-foot {
  text-align: right;
  margin-top: 8px;
}
</style>
