<template>
  <div class="result-panel">
    <div class="placeholder-cards">
      <div class="card" v-for="i in 3" :key="i">
        <div class="day-badge">Day {{ i }}</div>
        <div class="card-content">
          <h4>M3 行程卡片占位</h4>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.result-panel {
  display: flex;
  overflow-x: auto;
  gap: 16px;
  padding-bottom: 8px; /* For scrollbar if any */
}
.card {
  min-width: 200px;
  background: #fff;
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.05);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.day-badge {
  background-color: #f0f2f5;
  color: #606266;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  width: fit-content;
}
.card-content h4 {
  margin: 0;
  font-size: 14px;
  color: #303133;
}
</style>
