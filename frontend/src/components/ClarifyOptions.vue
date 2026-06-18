<template>
  <div v-if="clarify && clarify.options && clarify.options.length" class="clarify-options">
    <el-radio-group v-model="picked" @change="onPick">
      <el-radio-button v-for="opt in clarify.options" :key="opt" :value="opt">{{ opt }}</el-radio-button>
    </el-radio-group>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useTripStore } from '../stores/trip'

const props = defineProps<{ send: (msg: string) => void }>()
const tripStore = useTripStore()
const clarify = computed(() => tripStore.clarifyPending)
const picked = ref('')

const onPick = (val: string) => { props.send(val); picked.value = '' }
</script>

<style scoped>
.clarify-options { padding: 8px 16px; display: flex; gap: 8px; flex-wrap: wrap; }
</style>
