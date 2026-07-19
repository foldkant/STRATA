import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'

export function useRouteMenu() {
  const route = useRoute()
  const isOpen = ref(false)

  watch(() => route.fullPath, () => {
    isOpen.value = false
  })

  function close() {
    isOpen.value = false
  }

  function toggle() {
    isOpen.value = !isOpen.value
  }

  return { isOpen, close, toggle }
}
