<script setup lang="ts">
import SyncView from '@shared/till/SyncView.vue'
import { useTill } from '../state'

const till = useTill()
</script>

<template>
  <SyncView :till="till" />
</template>
