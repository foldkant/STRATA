<script setup lang="ts">
import {
  evaluationNotAssessedOptions,
  type EvaluationCriterionDisplay,
  type EvaluationNotAssessedEntry,
  type EvaluationNotAssessedReasonCode
} from '@/domain/evaluation'

const props = withDefaults(defineProps<{
  criterion: EvaluationCriterionDisplay
  rating?: number
  notAssessed?: EvaluationNotAssessedEntry | null
  disabled?: boolean
}>(), {
  rating: 0,
  notAssessed: null,
  disabled: false
})

const emit = defineEmits<{
  rating: [criterionId: string, value: number]
  notAssessed: [criterionId: string, value: EvaluationNotAssessedEntry | null]
}>()

function setRating(value: number) {
  if (props.disabled) return
  emit('notAssessed', props.criterion.id, null)
  emit('rating', props.criterion.id, value)
}

function toggleNotAssessed() {
  if (props.disabled) return
  emit(
    'notAssessed',
    props.criterion.id,
    props.notAssessed ? null : { reason: 'no_evidence', note: '' }
  )
}

function updateReason(reason: EvaluationNotAssessedReasonCode) {
  emit('notAssessed', props.criterion.id, {
    reason,
    note: props.notAssessed?.note || ''
  })
}

function updateNote(note: string) {
  emit('notAssessed', props.criterion.id, {
    reason: props.notAssessed?.reason || 'no_evidence',
    note
  })
}
</script>

<template>
  <article class="evaluation-rating-item" :class="{ skipped: notAssessed }">
    <div class="evaluation-rating-copy">
      <strong>{{ criterion.title }}</strong>
      <span>{{ criterion.description || '请根据实际材料选择 1-5 星。' }}</span>
      <details v-if="criterion.level_descriptions?.length || criterion.skip_condition">
        <summary>查看评价说明</summary>
        <ol v-if="criterion.level_descriptions?.length">
          <li v-for="(description, index) in criterion.level_descriptions" :key="index">
            <b>{{ index + 1 }} 星</b>
            <span>{{ description }}</span>
          </li>
        </ol>
        <p v-if="criterion.skip_condition">暂不评价：{{ criterion.skip_condition }}</p>
      </details>
    </div>

    <div class="evaluation-rating-actions">
      <div class="star-rating-control" role="radiogroup" :aria-label="criterion.title">
        <button
          v-for="value in 5"
          :key="`${criterion.id}-${value}`"
          type="button"
          role="radio"
          :disabled="disabled"
          :class="{ active: !notAssessed && rating >= value }"
          :aria-checked="!notAssessed && rating === value"
          :aria-label="`${value} 星`"
          @click="setRating(value)"
        >
          ★
        </button>
      </div>
      <button
        class="not-assessed-button"
        type="button"
        :disabled="disabled"
        :class="{ active: notAssessed }"
        :aria-pressed="Boolean(notAssessed)"
        @click="toggleNotAssessed"
      >
        {{ notAssessed ? '取消暂不评价' : '暂不评价' }}
      </button>
    </div>

    <div v-if="notAssessed" class="not-assessed-fields">
      <label>
        <span>原因</span>
        <select
          :value="notAssessed.reason"
          :disabled="disabled"
          @change="updateReason(($event.target as HTMLSelectElement).value as EvaluationNotAssessedReasonCode)"
        >
          <option v-for="item in evaluationNotAssessedOptions" :key="item.value" :value="item.value">
            {{ item.label }}
          </option>
        </select>
      </label>
      <label>
        <span>{{ notAssessed.reason === 'other' ? '说明（必填）' : '补充说明' }}</span>
        <input
          :value="notAssessed.note"
          :disabled="disabled"
          maxlength="200"
          placeholder="可简要说明实际情况"
          @input="updateNote(($event.target as HTMLInputElement).value)"
        />
      </label>
    </div>
  </article>
</template>

<style scoped>
.evaluation-rating-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px 20px;
  padding: 14px 0;
  border-bottom: 1px solid var(--line);
}

.evaluation-rating-item.skipped {
  padding-inline: 12px;
  border: 1px solid #fcd34d;
  border-radius: 6px;
  background: #fffbeb;
}

.evaluation-rating-copy {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.evaluation-rating-copy > span {
  color: var(--muted);
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.evaluation-rating-copy details {
  margin-top: 4px;
  color: #475569;
}

.evaluation-rating-copy summary {
  width: fit-content;
  min-height: 32px;
  display: flex;
  align-items: center;
  color: var(--primary-dark);
  cursor: pointer;
}

.evaluation-rating-copy ol {
  display: grid;
  gap: 6px;
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
}

.evaluation-rating-copy li {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr);
  gap: 8px;
  line-height: 1.5;
}

.evaluation-rating-copy details p {
  margin: 8px 0 0;
}

.evaluation-rating-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.evaluation-rating-item .star-rating-control button {
  width: 44px;
  height: 44px;
}

.evaluation-rating-item button:focus-visible,
.evaluation-rating-item select:focus-visible,
.evaluation-rating-item input:focus-visible,
.evaluation-rating-copy summary:focus-visible {
  outline: 3px solid rgb(37 99 235 / 28%);
  outline-offset: 2px;
}

.not-assessed-button {
  min-height: 44px;
  padding: 0 12px;
  border: 1px solid #d1d9e6;
  border-radius: 6px;
  color: #475569;
  background: #fff;
  cursor: pointer;
}

.not-assessed-button.active {
  border-color: #d97706;
  color: #92400e;
  background: #fef3c7;
}

.not-assessed-fields {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: minmax(180px, 0.7fr) minmax(240px, 1.3fr);
  gap: 12px;
}

.not-assessed-fields label {
  display: grid;
  gap: 6px;
}

.not-assessed-fields label > span {
  color: #92400e;
  font-size: 13px;
  font-weight: 700;
}

.not-assessed-fields select,
.not-assessed-fields input {
  width: 100%;
  min-height: 44px;
  padding: 0 10px;
  border: 1px solid #d8b45b;
  border-radius: 6px;
  color: var(--text);
  background: #fff;
}

@container (max-width: 560px) {
  .evaluation-rating-item {
    grid-template-columns: 1fr;
  }

  .evaluation-rating-actions {
    justify-content: flex-start;
    flex-wrap: wrap;
  }

  .not-assessed-fields {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .evaluation-rating-item {
    grid-template-columns: 1fr;
  }

  .evaluation-rating-actions {
    align-items: flex-start;
    flex-direction: column;
  }

  .not-assessed-fields {
    grid-template-columns: 1fr;
  }
}
</style>
