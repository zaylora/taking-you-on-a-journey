<template>
  <div class="map-view">
    <div class="map-placeholder-content">
      <el-icon :size="48" color="#909399"><MapLocation /></el-icon>
      <h3>地图预览 (M3)</h3>
    </div>
  </div>
</template>

<script setup lang="ts">
import { MapLocation } from '@element-plus/icons-vue'
</script>

<style scoped>
.map-view {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: #e8eaed; /* placeholder map color */
  display: flex;
  align-items: center;
  justify-content: center;
}
.map-placeholder-content {
  text-align: center;
  color: #909399;
}
.map-placeholder-content h3 {
  margin-top: 16px;
  font-weight: 500;
}
</style>
