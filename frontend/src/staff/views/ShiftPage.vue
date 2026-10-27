<script setup lang="ts">
import ShiftView from '@shared/till/ShiftView.vue'
import { useTill } from '../state'

const till = useTill()
</script>

<template>
  <ShiftView :till="till" />
</template>
