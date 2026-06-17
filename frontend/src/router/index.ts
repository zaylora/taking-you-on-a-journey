import { createRouter, createWebHistory } from 'vue-router'
// 只是一个占位路由，因为这是一个单页应用
const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('../App.vue') // 或者我们可以留空且不使用 router-view
    }
  ]
})

export default router
