<script setup lang="ts">
import { computed } from 'vue'
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

const curriculumAlignment = computed(() => props.criterion.curriculum_alignment)
const coreCompetencyLabels = computed(() => {
  const labels = (curriculumAlignment.value?.core_competencies || []).flatMap((item) => (
    item.elements?.length ? item.elements : [item.title]
  ))
  return Array.from(new Set(labels.filter(Boolean)))
})

function pageLabel(start: number, end: number) {
  return start === end ? `第 ${start} 页` : `第 ${start}—${end} 页`
}

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
    <div class="evaluation-alignment-grid">
      <section class="evaluation-alignment-foundation">
        <header><span>左 · 课标依据</span><strong>核心素养与学习目标</strong></header>
        <ul v-if="coreCompetencyLabels.length">
          <li v-for="label in coreCompetencyLabels" :key="label">{{ label }}</li>
        </ul>
        <p v-else>尚未提供可显示的核心素养要素。</p>
        <div v-for="goal in curriculumAlignment?.learning_goals || []" :key="goal.code">
          <b>{{ goal.code }} · {{ goal.title }}</b>
          <span>{{ goal.description }}</span>
        </div>
      </section>

      <section class="evaluation-rating-copy">
        <header><span>中 · 评价指标</span><strong>{{ criterion.title }}</strong></header>
        <p>{{ criterion.description || '请依据本次形成的评价材料判断学生的可观察表现。' }}</p>
        <small v-if="criterion.skip_condition">暂不评价条件：{{ criterion.skip_condition }}</small>
      </section>

      <section class="evaluation-rating-choice">
        <header><span>右 · 表现水平</span><strong>选择本次课堂表现</strong></header>
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
        <div class="evaluation-quality-reference">
          <b>学业质量参照</b>
          <template v-if="curriculumAlignment?.academic_quality?.length">
            <span v-for="item in curriculumAlignment.academic_quality" :key="item.node_id">
              {{ item.title }} · {{ pageLabel(item.page_start, item.page_end) }}
              <template v-if="item.level_labels.length">（{{ item.level_labels.join('、') }}）</template>
            </span>
          </template>
          <span v-else>尚未显示可追溯的学业质量条目。</span>
          <small>{{ curriculumAlignment?.quality_mapping_note || '1—5 星是本评价标准的课堂表现水平，不直接等同于课程标准中的学业质量等级。' }}</small>
        </div>
      </section>
    </div>

    <details v-if="criterion.level_descriptions?.length" class="evaluation-level-matrix" open>
      <summary>对照 1—5 星可观察表现</summary>
      <ol>
        <li v-for="(description, index) in criterion.level_descriptions" :key="index" :class="{ selected: !notAssessed && rating === index + 1 }">
          <b>{{ index + 1 }} 星</b>
          <span>{{ description }}</span>
        </li>
      </ol>
    </details>

    <div v-if="notAssessed" class="not-assessed-fields">
      <label>
        <span>原因</span>
        <AppSelect
          :value="notAssessed.reason"
          :disabled="disabled"
          @change="updateReason(($event.target as HTMLSelectElement).value as EvaluationNotAssessedReasonCode)"
        >
          <option v-for="item in evaluationNotAssessedOptions" :key="item.value" :value="item.value">
            {{ item.label }}
          </option>
        </AppSelect>
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
  gap: 14px;
  padding: 16px 0;
  border-bottom: 1px solid var(--line);
  container-type: inline-size;
}

.evaluation-rating-item.skipped {
  padding-inline: 12px;
  border: 1px solid #fcd34d;
  border-radius: 6px;
  background: #fffbeb;
}

.evaluation-alignment-grid {
  display: grid;
  grid-template-columns: minmax(180px, 0.9fr) minmax(240px, 1.25fr) minmax(250px, 1fr);
  gap: 0;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}

.evaluation-alignment-grid > section {
  min-width: 0;
  display: grid;
  align-content: start;
  gap: 9px;
  padding: 14px;
  border-right: 1px solid var(--line);
}

.evaluation-alignment-grid > section:last-child {
  border-right: 0;
}

.evaluation-alignment-grid header {
  display: grid;
  gap: 3px;
}

.evaluation-alignment-grid header > span {
  color: var(--primary);
  font-size: 12px;
  font-weight: 800;
}

.evaluation-alignment-foundation {
  background: #f4f7f4;
}

.evaluation-alignment-foundation ul {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.evaluation-alignment-foundation li {
  border: 1px solid #c5d6cc;
  border-radius: 999px;
  padding: 3px 7px;
  background: #eef5f1;
  color: #315f50;
  font-size: 12px;
}

.evaluation-alignment-foundation p,
.evaluation-rating-copy p {
  margin: 0;
  color: #475569;
  line-height: 1.55;
}

.evaluation-alignment-foundation > div {
  display: grid;
  gap: 3px;
  border-top: 1px solid #d8e4dc;
  padding-top: 8px;
}

.evaluation-alignment-foundation > div span {
  color: #475569;
  font-size: 13px;
  line-height: 1.5;
}

.evaluation-rating-copy small {
  border-left: 3px solid #d97706;
  padding: 6px 8px;
  background: #fffbeb;
  color: #92400e;
  line-height: 1.55;
}

.evaluation-rating-choice {
  background: #fcfcfd;
}

.evaluation-quality-reference {
  display: grid;
  gap: 4px;
  border-top: 1px solid var(--line);
  padding-top: 9px;
}

.evaluation-quality-reference span,
.evaluation-quality-reference small {
  color: #475569;
  font-size: 12px;
  line-height: 1.45;
}

.evaluation-quality-reference small {
  color: #7c2d12;
}

.evaluation-level-matrix {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 0 12px 12px;
  color: #475569;
}

.evaluation-level-matrix summary {
  min-height: 42px;
  display: flex;
  align-items: center;
  color: var(--primary-dark);
  font-weight: 700;
  cursor: pointer;
}

.evaluation-level-matrix ol {
  display: grid;
  grid-template-columns: repeat(5, minmax(150px, 1fr));
  gap: 8px;
  margin: 0;
  padding: 0;
  overflow-x: auto;
  list-style: none;
}

.evaluation-level-matrix li {
  display: grid;
  align-content: start;
  gap: 6px;
  border: 1px solid #d7e0da;
  border-radius: 6px;
  padding: 9px;
  background: #f8fafc;
  line-height: 1.5;
}

.evaluation-level-matrix li.selected {
  border-color: #78978c;
  background: #edf4f0;
  color: #0d352e;
}

.evaluation-rating-actions {
  display: flex;
  align-items: flex-start;
  flex-direction: column;
  gap: 10px;
}

.evaluation-rating-item .star-rating-control button {
  width: 44px;
  height: 44px;
}

.evaluation-rating-item button:focus-visible,
.evaluation-rating-item select:focus-visible,
.evaluation-rating-item input:focus-visible,
.evaluation-level-matrix summary:focus-visible {
  outline: 3px solid rgb(23 72 63 / 24%);
  outline-offset: 2px;
}

.not-assessed-button {
  min-height: 44px;
  padding: 0 12px;
  border: 1px solid #d1dbd5;
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

@container (max-width: 760px) {
  .evaluation-alignment-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .evaluation-rating-choice {
    grid-column: 1 / -1;
    border-top: 1px solid var(--line);
  }

  .evaluation-alignment-grid > section:nth-child(2) {
    border-right: 0;
  }
}

@container (max-width: 520px) {
  .evaluation-alignment-grid {
    grid-template-columns: 1fr;
  }

  .evaluation-alignment-grid > section {
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .evaluation-alignment-grid > section:last-child {
    border-bottom: 0;
  }

  .evaluation-rating-choice {
    grid-column: auto;
    border-top: 0;
  }

  .not-assessed-fields {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .evaluation-alignment-grid {
    grid-template-columns: 1fr;
  }

  .evaluation-alignment-grid > section {
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .evaluation-alignment-grid > section:last-child {
    border-bottom: 0;
  }

  .not-assessed-fields {
    grid-template-columns: 1fr;
  }
}
</style>
