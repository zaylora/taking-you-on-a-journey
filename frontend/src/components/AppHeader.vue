<template>
  <header class="app-header">
    <div class="logo-area">
      <!-- Icon placeholder -->
      <el-icon :size="24" color="#409eff"><Promotion /></el-icon>
      <h1>带你去旅行</h1>
      <nav class="nav-links">
        <a href="#" class="active">发现</a>
        <a href="#">我的行程</a>
      </nav>
    </div>
    <div class="user-area">
      <el-icon :size="20"><Moon /></el-icon>
      <el-icon :size="20"><Location /></el-icon>
      <el-avatar :size="32" src="https://cube.elemecdn.com/0/88/03b0d39583f48206768a7534e55bcpng.png" />
    </div>
  </header>
</template>

<script setup lang="ts">
import { Promotion, Moon, Location } from '@element-plus/icons-vue'
</script>

<style scoped>
.app-header {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  border-bottom: 1px solid #ebeef5;
  background-color: #fff;
  z-index: 10;
}
.logo-area {
  display: flex;
  align-items: center;
  gap: 12px;
}
.logo-area h1 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: #303133;
  margin-right: 32px;
}
.nav-links {
  display: flex;
  gap: 24px;
}
.nav-links a {
  text-decoration: none;
  color: #606266;
  font-size: 14px;
  font-weight: 500;
}
.nav-links a.active {
  color: #409eff;
  border-bottom: 2px solid #409eff;
  padding-bottom: 20px; /* Align border with header bottom */
  margin-bottom: -20px;
}
.user-area {
  display: flex;
  align-items: center;
  gap: 20px;
  color: #606266;
}
</style>
