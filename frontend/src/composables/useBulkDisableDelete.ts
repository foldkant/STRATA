import { type ComputedRef, type Ref } from 'vue'

type BulkResult = {
  updated_count?: number
  deleted_count?: number
  message?: string
}

type ConfirmFn = (title: string, message: string, action: () => Promise<void>, danger?: boolean) => void

export function useBulkDisableDelete<T extends { id: number }>(options: {
  entityLabel: string
  selectedIds: Ref<number[]>
  selectedRows: ComputedRef<T[]>
  selectedCount: ComputedRef<number>
  notice: Ref<string>
  ask: ConfirmFn
  clearSelection: () => void
  isActive: (row: T) => boolean
  bulkDisable: (ids: number[]) => Promise<BulkResult>
  bulkDelete: (ids: number[]) => Promise<BulkResult>
  activeDeleteMessage?: string
  deleteMessage?: string
}) {
  function disableSelected() {
    if (!options.selectedCount.value) {
      options.notice.value = `请先选择${options.entityLabel}。`
      return
    }
    options.ask(`批量停用${options.entityLabel}`, `确认停用已选 ${options.selectedCount.value} 个${options.entityLabel}？`, async () => {
      const result = await options.bulkDisable(options.selectedIds.value)
      options.notice.value = result.updated_count
        ? `已停用 ${result.updated_count} 个${options.entityLabel}。`
        : `所选${options.entityLabel}无需停用。`
      options.clearSelection()
    })
  }

  function deleteSelected() {
    if (!options.selectedCount.value) {
      options.notice.value = `请先选择${options.entityLabel}。`
      return
    }
    const activeRows = options.selectedRows.value.filter(options.isActive)
    if (activeRows.length) {
      options.ask(
        `先停用${options.entityLabel}`,
        `已选${options.entityLabel}中有 ${activeRows.length} 个仍处于启用状态。确认后系统只执行批量停用；停用完成后请重新勾选并再次删除。`,
        async () => {
          const result = await options.bulkDisable(options.selectedIds.value)
          options.notice.value = result.updated_count
            ? `已停用 ${result.updated_count} 个${options.entityLabel}，请重新勾选后删除。`
            : `所选${options.entityLabel}无需停用。`
          options.clearSelection()
        },
        true
      )
      return
    }

    options.ask(
      `批量删除${options.entityLabel}`,
      options.deleteMessage || `确认删除已选 ${options.selectedCount.value} 个已停用${options.entityLabel}？已有业务数据时系统会保留停用状态。`,
      async () => {
        const result = await options.bulkDelete(options.selectedIds.value)
        options.notice.value = result.message || `已删除 ${result.deleted_count || 0} 个${options.entityLabel}。`
        options.clearSelection()
      },
      true
    )
  }

  return {
    disableSelected,
    deleteSelected
  }
}
