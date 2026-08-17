<template>
  <el-container class="layout">
    <el-header class="header gov-header-banner">
      <div class="brand" @click="$router.push('/public')">
        <span class="logo">🏛️</span>
        <span class="title">一网通办 · 群众端</span>
      </div>
      <div class="header-right">
        <el-button text @click="$router.push('/public/chat')" style="color:#fff">💬 智能问答</el-button>
        <el-button text @click="back" style="color:#fff">切换角色</el-button>
      </div>
    </el-header>
    <el-container>
      <el-aside width="200px" class="aside">
        <el-menu :default-active="$route.path" router class="menu">
          <el-menu-item index="/public/search"><el-icon><Search /></el-icon>事项搜索</el-menu-item>
          <el-menu-item index="/public/chat"><el-icon><ChatDotRound /></el-icon>智能问答</el-menu-item>
          <el-menu-item index="/public/history"><el-icon><Clock /></el-icon>历史咨询</el-menu-item>
        </el-menu>
      </el-aside>
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
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 60px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.logo {
  font-size: 24px;
}
.title {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 1px;
}
.aside {
  background: #fff;
  border-right: 1px solid #ebeef5;
}
.menu {
  border-right: none;
}
.main {
  padding: 16px;
  overflow: auto;
}
</style>
