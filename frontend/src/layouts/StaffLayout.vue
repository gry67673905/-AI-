<template>
  <el-container class="layout">
    <el-aside width="200px" class="aside gov-header-banner">
      <div class="logo-area">
        <span class="logo">🏛️</span>
        <div>
          <div class="sys">一网通办</div>
          <div class="sub">工作人员端</div>
        </div>
      </div>
      <el-menu :default-active="$route.path" router background-color="transparent" text-color="#cfd8ec" active-text-color="#fff" class="menu">
        <el-menu-item index="/staff/workbench"><el-icon><Service /></el-icon>咨询工作台</el-menu-item>
        <el-menu-item index="/staff/cases"><el-icon><FolderChecked /></el-icon>办件处理</el-menu-item>
        <el-menu-item index="/staff/knowledge"><el-icon><Collection /></el-icon>知识辅助</el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <div class="page-name">工作人员端</div>
        <el-button text @click="back">退出登录</el-button>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { useAppStore } from '../store/app'

const router = useRouter()
const store = useAppStore()

function back() {
  store.logout()
  router.push('/')
}
</script>

<style scoped>
.layout {
  height: 100vh;
}
.aside {
  display: flex;
  flex-direction: column;
}
.logo-area {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 20px 16px;
  color: #fff;
}
.logo {
  font-size: 28px;
}
.sys {
  font-size: 16px;
  font-weight: 600;
}
.sub {
  font-size: 12px;
  opacity: 0.8;
}
.menu {
  border-right: none;
}
.menu :deep(.el-menu-item) {
  color: #cfd8ec;
}
.menu :deep(.el-menu-item.is-active) {
  background: rgba(255, 255, 255, 0.15);
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #ebeef5;
  height: 56px;
}
.page-name {
  font-size: 16px;
  font-weight: 600;
  color: #1f3b73;
}
.main {
  padding: 16px;
  overflow: auto;
}
</style>
