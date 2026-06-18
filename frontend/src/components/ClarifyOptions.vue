<template>
  <div v-if="clarify" class="clarify-options">
    <el-radio-group v-if="clarify.options.length" v-model="picked" @change="onPick">
      <el-radio-button v-for="opt in clarify.options" :key="opt" :value="opt">{{ opt }}</el-radio-button>
    </el-radio-group>
    <div v-else class="free-input">
      <el-input v-model="freeText" placeholder="请输入…" @keyup.enter="onFree" />
      <el-button type="primary" @click="onFree">发送</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useTripStore } from '../stores/trip'

const props = defineProps<{ send: (msg: string) => void }>()
const tripStore = useTripStore()
const clarify = computed(() => tripStore.clarifyPending)
const picked = ref('')
const freeText = ref('')

const onPick = (val: string) => { props.send(val); picked.value = '' }
const onFree = () => { if (freeText.value.trim()) { props.send(freeText.value); freeText.value = '' } }
</script>

<style scoped>
.clarify-options { padding: 8px 16px; display: flex; gap: 8px; flex-wrap: wrap; }
.free-input { display: flex; gap: 8px; width: 100%; }
</style>
