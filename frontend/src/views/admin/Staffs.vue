<template>
  <div class="page-container">
    <h2 class="page-title">工作人员管理</h2>
    <p class="page-sub">维护工作人员信息、所属部门与窗口</p>

    <div class="toolbar">
      <el-input v-model="kw" placeholder="搜索姓名/电话" clearable style="width: 260px" prefix-icon="Search" />
      <div class="spacer"></div>
      <el-button type="primary" @click="openAdd"><el-icon><Plus /></el-icon>新增人员</el-button>
    </div>

    <el-table :data="filtered" border>
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="name" label="姓名" width="100" />
      <el-table-column label="所属部门" min-width="180">
        <template #default="{ row }">{{ deptName(row.deptId) }}</template>
      </el-table-column>
      <el-table-column label="所属窗口" min-width="150">
        <template #default="{ row }">{{ windowName(row.windowId) }}</template>
      </el-table-column>
      <el-table-column prop="role" label="角色" width="120" />
      <el-table-column prop="phone" label="联系电话" width="150" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-switch v-model="row.status" @change="saveStaff(row)" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-button type="primary" text @click="openEdit(row)">编辑</el-button>
          <el-button type="danger" text @click="del(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" :title="form.id ? '编辑人员' : '新增人员'" width="520px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="姓名"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="所属部门">
          <el-select v-model="form.deptId" style="width:100%" @change="form.windowId = null">
            <el-option v-for="d in depts" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="所属窗口">
          <el-select v-model="form.windowId" style="width:100%">
            <el-option v-for="w in deptWindows" :key="w.id" :label="w.name" :value="w.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="角色"><el-input v-model="form.role" /></el-form-item>
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
import { getStaffs, getDepts, getWindows, saveStaff, deleteStaff, deptName, windowName } from '../../api'

const list = ref([])
const depts = ref([])
const windows = ref([])
const kw = ref('')
const dialog = ref(false)
const form = ref({})

const filtered = computed(() => {
  if (!kw.value) return list.value
  return list.value.filter((s) => s.name.includes(kw.value) || s.phone.includes(kw.value))
})

const deptWindows = computed(() => windows.value.filter((w) => w.deptId === form.value.deptId))

async function load() { list.value = await getStaffs() }

function openAdd() { form.value = { name: '', deptId: null, windowId: null, role: '', phone: '', status: true }; dialog.value = true }
function openEdit(row) { form.value = { ...row }; dialog.value = true }

async function submit() {
  await saveStaff(form.value)
  ElMessage.success('已保存')
  dialog.value = false
  load()
}

async function del(row) {
  await ElMessageBox.confirm(`确认删除人员「${row.name}」？`, '提示', { type: 'warning' })
  await deleteStaff(row.id)
  ElMessage.success('已删除')
  load()
}

onMounted(async () => {
  load()
  depts.value = await getDepts()
  windows.value = await getWindows()
})
</script>
