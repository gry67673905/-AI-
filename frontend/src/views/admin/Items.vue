<template>
  <div class="page-container">
    <h2 class="page-title">政务事项管理</h2>
    <p class="page-sub">维护事项办理条件、材料清单、流程与注意事项</p>

    <div class="toolbar">
      <el-input v-model="kw" placeholder="搜索事项名称/编码" clearable style="width: 260px" prefix-icon="Search" />
      <el-select v-model="cat" placeholder="全部分类" clearable style="width: 160px">
        <el-option v-for="c in categoryOptions" :key="c" :label="c" :value="c" />
      </el-select>
      <div class="spacer"></div>
      <el-button type="primary" @click="openAdd"><el-icon><Plus /></el-icon>新增事项</el-button>
    </div>

    <el-table :data="filtered" border>
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="name" label="事项名称" min-width="200" show-overflow-tooltip />
      <el-table-column prop="code" label="编码" width="120" />
      <el-table-column label="分类" width="110">
        <template #default="{ row }"><el-tag size="small" type="primary">{{ row.category }}</el-tag></template>
      </el-table-column>
      <el-table-column label="部门" min-width="160">
        <template #default="{ row }">{{ deptName(row.deptId) }}</template>
      </el-table-column>
      <el-table-column prop="timeLimit" label="时限" width="120" />
      <el-table-column label="热门" width="70">
        <template #default="{ row }">
          <el-tag v-if="row.hot" type="danger" size="small">热门</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-button type="primary" text @click="openEdit(row)">编辑</el-button>
          <el-button type="danger" text @click="del(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" :title="form.id ? '编辑事项' : '新增事项'" width="760px" top="4vh">
      <el-form :model="form" label-width="96px">
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="事项名称"><el-input v-model="form.name" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="事项编码"><el-input v-model="form.code" /></el-form-item></el-col>
          <el-col :span="12">
            <el-form-item label="所属部门">
              <el-select v-model="form.deptId" style="width:100%">
                <el-option v-for="d in depts" :key="d.id" :label="d.name" :value="d.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="分类">
              <el-select v-model="form.category" style="width:100%">
                <el-option v-for="c in categoryOptions" :key="c" :label="c" :value="c" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12"><el-form-item label="服务对象"><el-input v-model="form.serviceObject" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="法律依据"><el-input v-model="form.legalBasis" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="办理时限"><el-input v-model="form.timeLimit" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="收费标准"><el-input v-model="form.charge" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="办理窗口"><el-input v-model="form.window" /></el-form-item></el-col>
          <el-col :span="12">
            <el-form-item label="热门事项"><el-switch v-model="form.hot" /></el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="办理条件">
          <el-select v-model="form.conditions" multiple filterable allow-create default-first-option placeholder="输入后回车添加条件" style="width:100%">
            <el-option v-for="c in form.conditions" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="注意事项"><el-input v-model="form.notice" type="textarea" :rows="2" /></el-form-item>

        <el-form-item label="材料清单">
          <div style="width:100%">
            <div v-for="(m, i) in form.materials" :key="i" class="row-line">
              <el-input v-model="m.name" placeholder="材料名称" style="width:200px" />
              <el-switch v-model="m.required" active-text="必需" style="margin:0 8px" />
              <el-input v-model="m.copies" placeholder="份数" style="width:130px" />
              <el-input v-model="m.note" placeholder="填写提示" style="flex:1" />
              <el-button type="danger" text @click="form.materials.splice(i, 1)">删</el-button>
            </div>
            <el-button size="small" @click="form.materials.push({ name: '', required: true, copies: '', sample: '', note: '' })">＋ 添加材料</el-button>
          </div>
        </el-form-item>

        <el-form-item label="办理流程">
          <div style="width:100%">
            <div v-for="(p, i) in form.process" :key="i" class="row-line">
              <el-input v-model="p.title" placeholder="环节名称" style="width:180px" />
              <el-input v-model="p.desc" placeholder="环节说明" style="flex:1" />
              <el-button type="danger" text @click="form.process.splice(i, 1)">删</el-button>
            </div>
            <el-button size="small" @click="form.process.push({ title: '', desc: '' })">＋ 添加环节</el-button>
          </div>
        </el-form-item>
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
import { getItems, getDepts, saveItem, deleteItem, deptName } from '../../api'
import { categoryOptions } from '../../mock/data'

const list = ref([])
const depts = ref([])
const kw = ref('')
const cat = ref('')
const dialog = ref(false)
const form = ref({})

const filtered = computed(() => {
  return list.value.filter((i) => {
    const hit = !kw.value || i.name.includes(kw.value) || i.code.includes(kw.value)
    const c = !cat.value || i.category === cat.value
    return hit && c
  })
})

async function load() { list.value = await getItems() }

function openAdd() {
  form.value = {
    name: '', code: '', deptId: null, category: '社会保障', serviceObject: '', legalBasis: '',
    timeLimit: '', charge: '免费', window: '', hot: false, conditions: [], notice: '',
    materials: [{ name: '', required: true, copies: '', sample: '', note: '' }],
    process: [{ title: '', desc: '' }]
  }
  dialog.value = true
}
function openEdit(row) {
  form.value = {
    ...row,
    conditions: [...(row.conditions || [])],
    materials: (row.materials || []).map((m) => ({ ...m })),
    process: (row.process || []).map((p) => ({ ...p }))
  }
  dialog.value = true
}

async function submit() {
  if (!form.value.name) { ElMessage.warning('请填写事项名称'); return }
  await saveItem(form.value)
  ElMessage.success('已保存')
  dialog.value = false
  load()
}

async function del(row) {
  await ElMessageBox.confirm(`确认删除事项「${row.name}」？`, '提示', { type: 'warning' })
  await deleteItem(row.id)
  ElMessage.success('已删除')
  load()
}

onMounted(async () => {
  load()
  depts.value = await getDepts()
})
</script>

<style scoped>
.row-line {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
</style>
