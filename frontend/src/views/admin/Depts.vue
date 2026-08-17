<template>
  <div class="page-container">
    <h2 class="page-title">部门管理</h2>
    <p class="page-sub">维护政务部门基础信息</p>

    <div class="toolbar">
      <el-input v-model="kw" placeholder="搜索部门名称/编码" clearable style="width: 260px" prefix-icon="Search" />
      <div class="spacer"></div>
      <el-button type="primary" @click="openAdd"><el-icon><Plus /></el-icon>新增部门</el-button>
    </div>

    <el-table :data="filtered" border>
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="name" label="部门名称" min-width="200" />
      <el-table-column prop="code" label="编码" width="100" />
      <el-table-column prop="leader" label="负责人" width="120" />
      <el-table-column prop="phone" label="联系电话" width="150" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-switch v-model="row.status" @change="saveDept(row)" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-button type="primary" text @click="openEdit(row)">编辑</el-button>
          <el-button type="danger" text @click="del(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" :title="form.id ? '编辑部门' : '新增部门'" width="520px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="部门名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="编码"><el-input v-model="form.code" /></el-form-item>
        <el-form-item label="负责人"><el-input v-model="form.leader" /></el-form-item>
        <el-form-item label="联系电话"><el-input v-model="form.phone" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getDepts, saveDept, deleteDept } from '../../api'

const list = ref([])
const kw = ref('')
const dialog = ref(false)
const form = ref({})

const filtered = computed(() => {
  if (!kw.value) return list.value
  return list.value.filter((d) => d.name.includes(kw.value) || d.code.includes(kw.value))
})

async function load() { list.value = await getDepts() }

function openAdd() { form.value = { name: '', code: '', leader: '', phone: '', status: true }; dialog.value = true }
function openEdit(row) { form.value = { ...row }; dialog.value = true }

async function submit() {
  await saveDept(form.value)
  ElMessage.success('已保存')
  dialog.value = false
  load()
}

async function del(row) {
  await ElMessageBox.confirm(`确认删除部门「${row.name}」？`, '提示', { type: 'warning' })
  await deleteDept(row.id)
  ElMessage.success('已删除')
  load()
}

onMounted(load)
</script>
