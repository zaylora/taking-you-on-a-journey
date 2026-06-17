<template>
  <aside class="app-sidebar">
    <div class="main-menus">
      <div class="menu-item active">
        <el-icon><ChatDotRound /></el-icon>
        <span>对话</span>
      </div>
      <div class="menu-item">
        <el-icon><Calendar /></el-icon>
        <span>行程</span>
      </div>
      <div class="menu-item">
        <el-icon><MapLocation /></el-icon>
        <span>地图</span>
      </div>
      <div class="menu-item">
        <el-icon><Star /></el-icon>
        <span>收藏</span>
      </div>
      <div class="menu-item">
        <el-icon><Setting /></el-icon>
        <span>设置</span>
      </div>
    </div>

    <div class="secondary-menus">
      <div class="section-title">旅行灵感</div>
      <div class="menu-item"><el-icon><LocationInformation /></el-icon>热门目的地</div>
      <div class="menu-item"><el-icon><Ticket /></el-icon>主题玩法</div>
      <div class="menu-item"><el-icon><Sunny /></el-icon>季节推荐</div>
      <div class="menu-item"><el-icon><Suitcase /></el-icon>周末短途</div>
      <div class="menu-item"><el-icon><Discount /></el-icon>亲子游</div>
      <div class="menu-item"><el-icon><Food /></el-icon>美食之旅</div>
    </div>

    <div class="tips-card">
      <div class="section-title">出行贴士</div>
      <p class="tips-text">东京5月天气舒适，平均气温18~24℃，建议携带轻便外套，并提前预订热门景点门票。</p>
      <!-- Optional: Add a small illustration here -->
    </div>
  </aside>
</template>

<script setup lang="ts">
import { 
  ChatDotRound, Calendar, MapLocation, Star, Setting,
  LocationInformation, Ticket, Sunny, Suitcase, Discount, Food
} from '@element-plus/icons-vue'
</script>

<style scoped>
.app-sidebar {
  width: 220px;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #ebeef5;
  background-color: #fafbfc;
  padding: 16px 12px;
  overflow-y: auto;
}
.menu-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border-radius: 8px;
  color: #606266;
  font-size: 14px;
  cursor: pointer;
  margin-bottom: 4px;
  transition: all 0.3s;
}
.menu-item:hover {
  background-color: #f0f2f5;
}
.menu-item.active {
  background-color: #ecf5ff;
  color: #409eff;
  font-weight: 500;
}
.secondary-menus {
  margin-top: 24px;
}
.section-title {
  font-size: 13px;
  color: #909399;
  padding: 0 12px;
  margin-bottom: 12px;
  font-weight: 500;
}
.tips-card {
  margin-top: auto;
  background-color: #fff;
  border-radius: 12px;
  padding: 16px;
  border: 1px solid #ebeef5;
}
.tips-text {
  font-size: 12px;
  color: #606266;
  line-height: 1.6;
  margin: 0;
}
</style>
