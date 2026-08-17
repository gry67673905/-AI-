import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'home',
    component: () => import('../views/Home.vue'),
    meta: { title: '角色选择' }
  },
  // ============ 群众端 ============
  {
    path: '/public',
    component: () => import('../layouts/PublicLayout.vue'),
    redirect: '/public/search',
    children: [
      { path: 'search', name: 'public-search', component: () => import('../views/public/Search.vue'), meta: { title: '事项搜索' } },
      { path: 'chat', name: 'public-chat', component: () => import('../views/public/Chat.vue'), meta: { title: '智能问答' } },
      { path: 'item/:id', name: 'public-item', component: () => import('../views/public/ItemDetail.vue'), meta: { title: '事项详情' } },
      { path: 'history', name: 'public-history', component: () => import('../views/public/History.vue'), meta: { title: '历史咨询' } }
    ]
  },
  // ============ 工作人员端 ============
  {
    path: '/staff',
    component: () => import('../layouts/StaffLayout.vue'),
    redirect: '/staff/workbench',
    children: [
      { path: 'workbench', name: 'staff-workbench', component: () => import('../views/staff/Workbench.vue'), meta: { title: '咨询工作台' } },
      { path: 'cases', name: 'staff-cases', component: () => import('../views/staff/Cases.vue'), meta: { title: '办件处理' } },
      { path: 'knowledge', name: 'staff-knowledge', component: () => import('../views/staff/Knowledge.vue'), meta: { title: '知识辅助' } }
    ]
  },
  // ============ 后台管理端 ============
  {
    path: '/admin',
    component: () => import('../layouts/AdminLayout.vue'),
    redirect: '/admin/dashboard',
    children: [
      { path: 'dashboard', name: 'admin-dashboard', component: () => import('../views/admin/Dashboard.vue'), meta: { title: '工作台' } },
      { path: 'depts', name: 'admin-depts', component: () => import('../views/admin/Depts.vue'), meta: { title: '部门管理' } },
      { path: 'windows', name: 'admin-windows', component: () => import('../views/admin/Windows.vue'), meta: { title: '窗口管理' } },
      { path: 'staffs', name: 'admin-staffs', component: () => import('../views/admin/Staffs.vue'), meta: { title: '工作人员管理' } },
      { path: 'items', name: 'admin-items', component: () => import('../views/admin/Items.vue'), meta: { title: '政务事项管理' } },
      { path: 'cases', name: 'admin-cases', component: () => import('../views/admin/Cases.vue'), meta: { title: '办件记录管理' } },
      { path: 'consultations', name: 'admin-consultations', component: () => import('../views/admin/Consultations.vue'), meta: { title: '群众咨询管理' } }
    ]
  },
  { path: '/:pathMatch(.*)*', redirect: '/' }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 })
})

router.afterEach((to) => {
  document.title = (to.meta.title ? to.meta.title + ' - ' : '') + '智慧政务“一网通办”AI助手'
})

export default router
