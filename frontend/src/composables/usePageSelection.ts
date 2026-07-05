import { computed, ref, type Ref } from 'vue'

export function usePageSelection<T extends { id: number }>(rows: Ref<T[]>) {
  const selectedIds = ref<number[]>([])
  const selectedIdSet = computed(() => new Set(selectedIds.value))
  const selectedRows = computed(() => rows.value.filter((row) => selectedIdSet.value.has(row.id)))
  const selectedCount = computed(() => selectedIds.value.length)
  const allPageSelected = computed(() => rows.value.length > 0 && rows.value.every((row) => selectedIdSet.value.has(row.id)))
  const partiallyPageSelected = computed(() => selectedCount.value > 0 && !allPageSelected.value)

  function toggleRow(id: number, checked: boolean) {
    const next = new Set(selectedIds.value)
    if (checked) {
      next.add(id)
    } else {
      next.delete(id)
    }
    selectedIds.value = Array.from(next)
  }

  function togglePage(checked: boolean) {
    const next = new Set(selectedIds.value)
    rows.value.forEach((row) => {
      if (checked) {
        next.add(row.id)
      } else {
        next.delete(row.id)
      }
    })
    selectedIds.value = Array.from(next)
  }

  function clearSelection() {
    selectedIds.value = []
  }

  return {
    selectedIds,
    selectedIdSet,
    selectedRows,
    selectedCount,
    allPageSelected,
    partiallyPageSelected,
    toggleRow,
    togglePage,
    clearSelection
  }
}
