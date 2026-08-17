<template>
  <div class="home">
    <div class="hero gov-header-banner">
      <h1>🏛️ 智慧政务「一网通办」AI助手</h1>
      <p>面向事项咨询 · 材料清单生成 · 流程导航 · 办件辅助的一体化智能服务平台</p>
    </div>

    <div class="roles">
      <el-card class="role-card" shadow="hover" @click="enter('public')">
        <el-icon :size="42" color="#2f5aa8"><User /></el-icon>
        <h3>群众端</h3>
        <p>事项搜索 · 智能问答<br />材料预填 · 流程查看 · 历史咨询</p>
      </el-card>
      <el-card class="role-card" shadow="hover" @click="enter('staff')">
        <el-icon :size="42" color="#2f5aa8"><Service /></el-icon>
        <h3>工作人员端</h3>
        <p>咨询工作台 · 办件处理<br />知识辅助 · 转人工接管</p>
      </el-card>
      <el-card class="role-card" shadow="hover" @click="enter('admin')">
        <el-icon :size="42" color="#2f5aa8"><Setting /></el-icon>
        <h3>后台管理端</h3>
        <p>部门 · 窗口 · 人员 · 事项<br />办件记录 · 群众咨询管理</p>
      </el-card>
    </div>

    <div class="footer-tip">
      演示项目 · 数据为本地模拟，可无缝对接后端 RESTful API
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { useAppStore } from '../store/app'

const router = useRouter()
const store = useAppStore()

function enter(role) {
  store.setRole(role)
  const map = { public: '/public', staff: '/staff', admin: '/admin' }
  router.push(map[role])
}
</script>

<style scoped>
.home {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}
.hero {
  padding: 64px 24px 56px;
  text-align: center;
}
.hero h1 {
  font-size: 34px;
  margin: 0 0 12px;
  letter-spacing: 2px;
}
.hero p {
  font-size: 15px;
  opacity: 0.9;
  margin: 0;
}
.roles {
  display: flex;
  gap: 24px;
  justify-content: center;
  flex-wrap: wrap;
  padding: 40px 24px;
}
.role-card {
  width: 260px;
  text-align: center;
  cursor: pointer;
  transition: transform 0.2s;
}
.role-card:hover {
  transform: translateY(-6px);
}
.role-card h3 {
  margin: 12px 0 8px;
  color: #1f3b73;
}
.role-card p {
  color: #909399;
  line-height: 1.8;
  margin: 0;
}
.footer-tip {
  text-align: center;
  color: #c0c4cc;
  font-size: 13px;
  margin-top: auto;
  padding: 24px;
}
</style>
