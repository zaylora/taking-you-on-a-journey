<template>
  <div class="app-container">
    <AppHeader />
    <div class="app-body">
      <AppSidebar />
      <div class="chat-section">
        <ChatPanel />
      </div>
      <div class="map-section">
        <MapView />
        <div class="map-overlays">
          <ResultPanel />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import AppHeader from './components/AppHeader.vue'
import AppSidebar from './components/AppSidebar.vue'
import ChatPanel from './components/ChatPanel.vue'
import MapView from './components/MapView.vue'
import ResultPanel from './components/ResultPanel.vue'
</script>

<style>
/* 全局样式重置与简单布局 */
html, body, #app {
  margin: 0;
  padding: 0;
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}
</style>

<style scoped>
.app-container {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
  background-color: #f5f7fa;
}

.app-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.chat-section {
  width: 380px;
  min-width: 380px;
  height: 100%;
  background-color: #fff;
  border-right: 1px solid #ebeef5;
  box-shadow: 2px 0 8px rgba(0,0,0,0.02);
  z-index: 5;
}

.map-section {
  flex: 1;
  position: relative;
  display: flex;
  flex-direction: column;
}

.map-overlays {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 24px;
  pointer-events: none; /* Let clicks pass through to map where there are no overlays */
}
.map-overlays > * {
  pointer-events: auto;
}
</style>
