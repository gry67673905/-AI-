<template>
  <div class="page-container">
    <h2 class="page-title">窗口管理</h2>
    <p class="page-sub">维护服务窗口信息与所属部门</p>

    <div class="toolbar">
      <el-input v-model="kw" placeholder="搜索窗口名称/位置" clearable style="width: 260px" prefix-icon="Search" />
      <div class="spacer"></div>
      <el-button type="primary" @click="openAdd"><el-icon><Plus /></el-icon>新增窗口</el-button>
    </div>

    <el-table :data="filtered" border>
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="name" label="窗口名称" min-width="160" />
      <el-table-column label="所属部门" min-width="180">
        <template #default="{ row }">{{ deptName(row.deptId) }}</template>
      </el-table-column>
      <el-table-column prop="location" label="位置" min-width="160" />
      <el-table-column prop="serviceScope" label="服务范围" min-width="200" show-overflow-tooltip />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-switch v-model="row.status" @change="saveWindow(row)" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-button type="primary" text @click="openEdit(row)">编辑</el-button>
          <el-button type="danger" text @click="del(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" :title="form.id ? '编辑窗口' : '新增窗口'" width="520px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="窗口名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="所属部门">
          <el-select v-model="form.deptId" style="width:100%">
            <el-option v-for="d in depts" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="位置"><el-input v-model="form.location" /></el-form-item>
        <el-form-item label="服务范围"><el-input v-model="form.serviceScope" type="textarea" :rows="2" /></el-form-item>
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
import { getWindows, getDepts, saveWindow, deleteWindow, deptName } from '../../api'

const list = ref([])
const depts = ref([])
const kw = ref('')
const dialog = ref(false)
const form = ref({})

const filtered = computed(() => {
  if (!kw.value) return list.value
  return list.value.filter((w) => w.name.includes(kw.value) || w.location.includes(kw.value))
})

async function load() { list.value = await getWindows() }

function openAdd() { form.value = { name: '', deptId: null, location: '', serviceScope: '', status: true }; dialog.value = true }
function openEdit(row) { form.value = { ...row }; dialog.value = true }

async function submit() {
  await saveWindow(form.value)
  ElMessage.success('已保存')
  dialog.value = false
  load()
}

async function del(row) {
  await ElMessageBox.confirm(`确认删除窗口「${row.name}」？`, '提示', { type: 'warning' })
  await deleteWindow(row.id)
  ElMessage.success('已删除')
  load()
}

onMounted(async () => {
  load()
  depts.value = await getDepts()
})
</script>
