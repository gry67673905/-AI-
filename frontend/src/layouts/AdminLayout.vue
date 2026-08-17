<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside gov-header-banner">
      <div class="logo-area">
        <span class="logo">🏛️</span>
        <div>
          <div class="sys">一网通办</div>
          <div class="sub">后台管理端</div>
        </div>
      </div>
      <el-menu :default-active="$route.path" router background-color="transparent" text-color="#cfd8ec" active-text-color="#fff" class="menu">
        <el-menu-item index="/admin/dashboard"><el-icon><Odometer /></el-icon>工作台</el-menu-item>
        <el-menu-item-group title="基础数据">
          <el-menu-item index="/admin/depts"><el-icon><OfficeBuilding /></el-icon>部门管理</el-menu-item>
          <el-menu-item index="/admin/windows"><el-icon><Grid /></el-icon>窗口管理</el-menu-item>
          <el-menu-item index="/admin/staffs"><el-icon><UserFilled /></el-icon>工作人员管理</el-menu-item>
        </el-menu-item-group>
        <el-menu-item-group title="业务管理">
          <el-menu-item index="/admin/items"><el-icon><Document /></el-icon>政务事项管理</el-menu-item>
          <el-menu-item index="/admin/cases"><el-icon><FolderChecked /></el-icon>办件记录管理</el-menu-item>
          <el-menu-item index="/admin/consultations"><el-icon><ChatLineSquare /></el-icon>群众咨询管理</el-menu-item>
        </el-menu-item-group>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <div class="page-name">{{ $route.meta.title }}</div>
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
  overflow-y: auto;
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
.menu :deep(.el-menu-item-group__title) {
  color: rgba(255, 255, 255, 0.5);
  padding-left: 16px;
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
