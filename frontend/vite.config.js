import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    host: true,
    open: false,
    // 后端联调时取消注释，把 /api 代理到 Spring Boot 服务
    // proxy: {
    //   '/api': { target: 'http://localhost:8080', changeOrigin: true }
    // }
  }
})
