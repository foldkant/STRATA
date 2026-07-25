<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError } from '@/api/client'
import {
  activateResearchRun,
  closeResearchRun,
  createResearchRun,
  createResearchStudy,
  freezeResearchCohort,
  getResearchOptions,
  getResearchStudies,
  getResearchStudy,
  lockResearchRunData,
  recordResearchGate,
  registerResearchProtocol,
  researchProtocolExportUrl,
  type ResearchOptions,
  type ResearchRun,
  type ResearchStudy
} from '@/api/research'
import NoticeLine from '@/components/NoticeLine.vue'
import { vModalFocus } from '@/directives/modalFocus'
import AppShell from '@/layouts/AppShell.vue'
import { schoolAdminNav } from './nav'

type ModalName = '' | 'study' | 'protocol' | 'condition' | 'class' | 'run' | 'lock'
type TabName = 'design' | 'classes' | 'implementation' | 'analysis'

const navItems = schoolAdminNav('/school-admin/research')
const options = ref<ResearchOptions | null>(null)
const studies = ref<ResearchStudy[]>([])
const selected = ref<ResearchStudy | null>(null)
const loading = ref(true)
const saving = ref(false)
const modal = ref<ModalName>('')
const activeTab = ref<TabName>('design')
const notice = ref('')
const noticeTone = ref<'success' | 'warning' | 'error' | 'info'>('info')
const lockTarget = ref<ResearchRun | null>(null)

const studyForm = ref({ code: '', title: '', subject_id: '', course_id: '', description: '' })
const protocolForm = ref({
  stage: 'E5', design_type: 'cluster_trial', research_questions: '', estimands: '', primary_outcomes: '',
  safety_outcomes: '', inclusion_criteria: '', exclusion_criteria: '', missing_data_plan: '',
  analysis_plan: '', stopping_rules: '', claim_boundary: '', ethics_approval_ref: '',
  ethics_approved_at: '', preregistration_ref: '', preregistered_at: '', consent_plan: '',
  evaluation_policy: '', content_band_policy: '', grouping_policy: ''
})
const conditionForm = ref({ gate: '', decision: 'approved', evidence_ref: '', note: '' })
const classForm = ref({
  class_group_id: '', arm: 'experiment', allocation_method: 'stratified_random',
  allocation_unit_code: '', development_site: true, prior_policy_access: false
})
const runForm = ref({ run_code: '', mode: 'cluster_trial', planned_start: '', planned_end: '' })
const lockForm = ref({
  decision_as_of: '', data_cutoff: '', row_count: 0, dataset_hash: '',
  data_files: '', variables: '', missingness_note: '', exclusion_note: ''
})

const currentProtocol = computed(() => selected.value?.current_protocol || null)
const protocolReady = computed(() => Boolean(currentProtocol.value))
const protocolContent = computed<Record<string, unknown>>(() => currentProtocol.value?.protocol || {})
const approvedConditionCount = computed(() => currentProtocol.value?.approved_gates.length || 0)
const requiredConditionCount = computed(() => currentProtocol.value?.required_gates.length || 0)
const classCount = computed(() => currentProtocol.value?.cohort_assignments?.length || 0)
const runCount = computed(() => currentProtocol.value?.runs?.length || 0)
const lockedRunCount = computed(() => currentProtocol.value?.runs?.filter((item) => item.data_lock).length || 0)

const stageDesignMap: Record<string, string> = {
  E1: 'blind_review', E2: 'retrospective', E3: 'shadow', E4: 'consultation',
  E5: 'cluster_trial', E6: 'external_confirmation'
}
const stageModeMap = { ...stageDesignMap }
const stageChoices = [
  { value: 'E1', label: '评价内容与使用方式审查' },
  { value: 'E2', label: '已有前测与评价材料检查' },
  { value: 'E3', label: '不影响教学安排的试运行' },
  { value: 'E4', label: '小范围教师辅助试用' },
  { value: 'E5', label: '实验班与对照班教育实验' },
  { value: 'E6', label: '外校独立复核' }
]
const experimentSteps = computed(() => [
  { title: '明确实验问题', done: Boolean(selected.value), detail: selected.value ? '已建立实验草稿' : '尚未建立' },
  { title: '确定共同测量', done: protocolReady.value, detail: protocolReady.value ? '前测、后测或问卷已写入方案' : '待完善方案' },
  { title: '安排参与班级', done: classCount.value > 0, detail: classCount.value ? classCount.value + ' 个班级' : '待安排实验班和对照班' },
  { title: '确认开展条件', done: requiredConditionCount.value > 0 && approvedConditionCount.value === requiredConditionCount.value, detail: protocolReady.value ? approvedConditionCount.value + '/' + requiredConditionCount.value + ' 项完成' : '待完善方案' },
  { title: '记录实际实施', done: runCount.value > 0, detail: runCount.value ? runCount.value + ' 次实施记录' : '待制定时间安排' },
  { title: '整理分析数据', done: lockedRunCount.value > 0, detail: lockedRunCount.value ? lockedRunCount.value + ' 份数据已确认' : '待完成共同后测或问卷' }
])

function lines(value: string) {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
}

function protocolList(key: string) {
  const value = protocolContent.value[key]
  if (Array.isArray(value)) return value.map(String)
  return value ? [String(value)] : []
}

function protocolText(key: string) {
  const value = protocolContent.value[key]
  return Array.isArray(value) ? value.map(String).join('；') : String(value || '')
}

function showError(error: unknown, fallback: string) {
  notice.value = error instanceof ApiError ? error.message : fallback
  noticeTone.value = 'error'
}

function closeModal() {
  if (!saving.value) modal.value = ''
}

function friendlyStage(stage: string) {
  return stageChoices.find((item) => item.value === stage)?.label || '教育实验方案'
}

function friendlyArm(arm: string) {
  return ({ experiment: '实验班', control: '对照班', observational: '观察班', external_confirmation: '外校复核班' } as Record<string, string>)[arm] || arm
}

function friendlyMethod(method: string) {
  return ({ random: '随机安排', stratified_random: '根据共同前测分层后随机安排', stepped_wedge: '分批进入实验安排', matched: '按班级情况匹配安排', observational: '按已有班级观察' } as Record<string, string>)[method] || method
}

function friendlyCondition(gate: string, fallback: string) {
  return ({
    ethics: '学生权益审查', preregistration: '实验方案预先登记', consent: '知情、退出与未成年人保护',
    instrument_review: '前测、后测与问卷质量检查', rater_training: '评价人员培训', data_governance: '数据使用与权限安排',
    data_quality: '数据完整性检查', power_analysis: '参与班级与样本数量论证', teacher_training: '任课教师实施培训',
    safety_monitoring: '学生权益与不利影响观察', policy_freeze: '教学与评价方案确认', allocation: '班级安排确认',
    external_independence: '外校独立性确认'
  } as Record<string, string>)[gate] || fallback
}

function statusTone(status: string) {
  if (['active', 'approved', 'data_locked'].includes(status)) return 'success'
  if (['closed', 'registered', 'completed'].includes(status)) return 'info'
  if (['rejected', 'failed'].includes(status)) return 'danger'
  return 'warning'
}

async function load(selectedId?: number) {
  loading.value = true
  try {
    const [nextOptions, nextStudies] = await Promise.all([getResearchOptions(), getResearchStudies()])
    options.value = nextOptions
    studies.value = nextStudies
    const id = selectedId || selected.value?.id || nextStudies[0]?.id
    selected.value = id ? await getResearchStudy(id) : null
  } catch (error) {
    showError(error, '教育实验信息加载失败。')
  } finally {
    loading.value = false
  }
}

async function selectStudy(id: number) {
  if (loading.value || selected.value?.id === id) return
  loading.value = true
  try {
    selected.value = await getResearchStudy(id)
    activeTab.value = 'design'
  } catch (error) {
    showError(error, '教育实验方案加载失败。')
  } finally {
    loading.value = false
  }
}

function openProtocolModal() {
  protocolForm.value.stage = currentProtocol.value?.stage || 'E5'
  protocolForm.value.design_type = stageDesignMap[protocolForm.value.stage]
  modal.value = 'protocol'
}

function updateStage() {
  protocolForm.value.design_type = stageDesignMap[protocolForm.value.stage]
}

async function saveStudy() {
  if (saving.value) return
  saving.value = true
  try {
    const created = await createResearchStudy({
      ...studyForm.value,
      subject_id: studyForm.value.subject_id || null,
      course_id: studyForm.value.course_id || null
    })
    modal.value = ''
    studyForm.value = { code: '', title: '', subject_id: '', course_id: '', description: '' }
    notice.value = '教育实验草稿已建立。下一步请确定共同前测、共同后测或问卷。'
    noticeTone.value = 'success'
    await load(created.id)
  } catch (error) {
    showError(error, '教育实验草稿建立失败。')
  } finally {
    saving.value = false
  }
}

async function saveProtocol() {
  if (!selected.value || saving.value) return
  saving.value = true
  const form = protocolForm.value
  try {
    const policy = ['E4', 'E5', 'E6'].includes(form.stage)
      ? { evaluation_policy: form.evaluation_policy, content_band_policy: form.content_band_policy, grouping_policy: form.grouping_policy }
      : {}
    await registerResearchProtocol(selected.value.id, {
      stage: form.stage,
      design_type: form.design_type,
      protocol: {
        research_questions: lines(form.research_questions), estimands: lines(form.estimands),
        primary_outcomes: lines(form.primary_outcomes), safety_outcomes: lines(form.safety_outcomes),
        inclusion_criteria: lines(form.inclusion_criteria), exclusion_criteria: lines(form.exclusion_criteria),
        missing_data_plan: form.missing_data_plan, analysis_plan: form.analysis_plan,
        stopping_rules: form.stopping_rules, claim_boundary: form.claim_boundary
      },
      ethics_approval_ref: form.ethics_approval_ref,
      ethics_approved_at: form.ethics_approved_at || null,
      preregistration_ref: form.preregistration_ref,
      preregistered_at: form.preregistered_at || null,
      consent_required: true,
      consent_plan: form.consent_plan,
      policy_snapshot: policy
    })
    modal.value = ''
    notice.value = '教育实验方案已经确认并保存为新版本。'
    noticeTone.value = 'success'
    await load(selected.value.id)
  } catch (error) {
    showError(error, '教育实验方案尚不能确认，请检查必填内容。')
  } finally {
    saving.value = false
  }
}

async function saveCondition() {
  if (!currentProtocol.value || saving.value) return
  saving.value = true
  try {
    await recordResearchGate(currentProtocol.value.id, conditionForm.value)
    modal.value = ''
    conditionForm.value = { gate: '', decision: 'approved', evidence_ref: '', note: '' }
    notice.value = '开展条件的核对结果已保存。'
    noticeTone.value = 'success'
    await load(selected.value!.id)
  } catch (error) {
    showError(error, '开展条件保存失败。')
  } finally {
    saving.value = false
  }
}

function openClassModal() {
  const external = currentProtocol.value?.stage === 'E6'
  classForm.value = {
    class_group_id: '', arm: external ? 'external_confirmation' : 'experiment',
    allocation_method: external ? 'observational' : 'stratified_random', allocation_unit_code: '',
    development_site: !external, prior_policy_access: false
  }
  modal.value = 'class'
}

async function saveClass() {
  if (!currentProtocol.value || saving.value) return
  saving.value = true
  try {
    await freezeResearchCohort(currentProtocol.value.id, classForm.value)
    modal.value = ''
    notice.value = '班级及其在教育实验中的安排已保存。'
    noticeTone.value = 'success'
    await load(selected.value!.id)
  } catch (error) {
    showError(error, '班级安排保存失败。')
  } finally {
    saving.value = false
  }
}

function openRunModal() {
  runForm.value = { run_code: '', mode: stageModeMap[currentProtocol.value?.stage || 'E5'], planned_start: '', planned_end: '' }
  modal.value = 'run'
}

async function saveRun() {
  if (!currentProtocol.value || saving.value) return
  saving.value = true
  try {
    await createResearchRun(currentProtocol.value.id, {
      ...runForm.value,
      planned_start: runForm.value.planned_start || null,
      planned_end: runForm.value.planned_end || null,
      decision_effect: currentProtocol.value.stage === 'E5'
    })
    modal.value = ''
    notice.value = '教育实验实施计划已建立；完成全部开展条件后才能开始。'
    noticeTone.value = 'success'
    await load(selected.value!.id)
  } catch (error) {
    showError(error, '实施计划建立失败。')
  } finally {
    saving.value = false
  }
}

async function changeRun(run: ResearchRun, action: 'activate' | 'close') {
  if (saving.value) return
  saving.value = true
  try {
    if (action === 'activate') await activateResearchRun(run.id)
    else await closeResearchRun(run.id)
    notice.value = action === 'activate' ? '本次教育实验实施已经开始。' : '本次实施已经结束，可以整理共同后测、问卷和实施记录。'
    noticeTone.value = 'success'
    await load(selected.value!.id)
  } catch (error) {
    showError(error, action === 'activate' ? '尚不能开始，请先完成开展条件。' : '结束实施失败。')
  } finally {
    saving.value = false
  }
}

function openLockModal(run: ResearchRun) {
  lockTarget.value = run
  lockForm.value = { decision_as_of: '', data_cutoff: '', row_count: 0, dataset_hash: '', data_files: '', variables: '', missingness_note: '', exclusion_note: '' }
  modal.value = 'lock'
}

async function saveDataLock() {
  if (!lockTarget.value || saving.value) return
  saving.value = true
  try {
    await lockResearchRunData(lockTarget.value.id, {
      decision_as_of: lockForm.value.decision_as_of,
      data_cutoff: lockForm.value.data_cutoff,
      row_count: lockForm.value.row_count,
      dataset_hash: lockForm.value.dataset_hash,
      dataset_manifest: { files: lines(lockForm.value.data_files) },
      variable_dictionary: lines(lockForm.value.variables).map((label, index) => ({ name: 'variable_' + (index + 1), label })),
      missingness_summary: { note: lockForm.value.missingness_note },
      exclusion_summary: { note: lockForm.value.exclusion_note }
    })
    modal.value = ''
    notice.value = '本次用于分析的数据范围已经确认。'
    noticeTone.value = 'success'
    await load(selected.value!.id)
  } catch (error) {
    showError(error, '分析数据确认失败。')
  } finally {
    saving.value = false
  }
}

onMounted(() => load())
</script>

<template>
  <AppShell title="教育实验" eyebrow="学校教学管理" :nav-items="navItems" shell-variant="school-admin" natural-scroll>
    <NoticeLine v-if="notice" :message="notice" :tone="noticeTone" />

    <section class="experiment-intro" aria-labelledby="experiment-intro-title">
      <div>
        <span>实验班与对照班</span>
        <h2 id="experiment-intro-title">围绕共同前测、教学实施和共同后测，完整记录一次教育实验</h2>
        <p>用于学校开展实验班与对照班研究。两类班级应使用一致的学习起点诊断；后测可以是测试、表现任务、作品评价或问卷，具体方式由研究问题决定。</p>
      </div>
      <button class="primary-button" type="button" @click="modal = 'study'">建立教育实验</button>
    </section>

    <ol class="experiment-steps" aria-label="教育实验工作流程">
      <li v-for="(item, index) in experimentSteps" :key="item.title" :class="{ done: item.done }">
        <span>{{ item.done ? '✓' : index + 1 }}</span>
        <div><strong>{{ item.title }}</strong><small>{{ item.detail }}</small></div>
      </li>
    </ol>

    <section class="experiment-layout">
      <aside class="experiment-list" aria-label="教育实验列表">
        <header><strong>教育实验</strong><span>{{ studies.length }} 项</span></header>
        <button
          v-for="study in studies"
          :key="study.id"
          type="button"
          :class="{ active: selected?.id === study.id }"
          @click="selectStudy(study.id)"
        >
          <strong>{{ study.title }}</strong>
          <span>{{ study.course_title || study.subject_name || '全校范围' }}</span>
          <small>{{ study.current_protocol ? friendlyStage(study.current_protocol.stage) : '实验草稿 · 待完善共同测量' }}</small>
        </button>
        <div v-if="!loading && !studies.length" class="list-empty">
          <strong>还没有教育实验</strong>
          <p>可以先建立草稿，确定研究问题后再安排班级。</p>
          <button class="secondary-button" type="button" @click="modal = 'study'">建立第一项实验</button>
        </div>
      </aside>

      <main v-if="selected" class="experiment-workspace">
        <header class="workspace-heading">
          <div>
            <span>{{ selected.code }}</span>
            <h2>{{ selected.title }}</h2>
            <p>{{ selected.description || '请补充这项教育实验希望回答的问题。' }}</p>
          </div>
          <button class="secondary-button" type="button" @click="openProtocolModal">{{ protocolReady ? '登记调整后的方案' : '完善实验方案' }}</button>
        </header>

        <nav class="experiment-tabs" aria-label="教育实验内容">
          <button type="button" :class="{ active: activeTab === 'design' }" @click="activeTab = 'design'">1 实验方案</button>
          <button type="button" :class="{ active: activeTab === 'classes' }" @click="activeTab = 'classes'">2 班级安排</button>
          <button type="button" :class="{ active: activeTab === 'implementation' }" @click="activeTab = 'implementation'">3 实施记录</button>
          <button type="button" :class="{ active: activeTab === 'analysis' }" @click="activeTab = 'analysis'">4 分析准备</button>
        </nav>

        <section v-if="activeTab === 'design'" class="workspace-section">
          <div v-if="currentProtocol" class="design-grid">
            <article>
              <span>实验类型</span>
              <strong>{{ friendlyStage(currentProtocol.stage) }}</strong>
              <small>当前采用第 {{ currentProtocol.version_no }} 版实验方案</small>
            </article>
            <article>
              <span>实验要回答的问题</span>
              <ul><li v-for="item in protocolList('research_questions')" :key="item">{{ item }}</li></ul>
            </article>
            <article>
              <span>共同前测与后测关注内容</span>
              <ul><li v-for="item in protocolList('primary_outcomes')" :key="item">{{ item }}</li></ul>
            </article>
            <article>
              <span>学生权益与实施影响</span>
              <ul><li v-for="item in protocolList('safety_outcomes')" :key="item">{{ item }}</li></ul>
            </article>
          </div>
          <div v-else class="guided-empty">
            <strong>草稿已经建立，下一步是把“比较什么、怎样共同测量”说清楚</strong>
            <p>建议先确定同一份学习起点诊断，再明确后测使用测试、作品、操作表现还是问卷。尚未确认方案前，系统不会安排任何班级。</p>
            <button class="primary-button" type="button" @click="openProtocolModal">完善实验方案</button>
          </div>

          <header v-if="currentProtocol" class="section-heading">
            <div><h3>开展条件</h3><p>开始实验前逐项确认学生权益、测量工具、教师培训和班级安排。</p></div>
            <button class="primary-button" type="button" @click="modal = 'condition'">记录核对结果</button>
          </header>
          <div v-if="currentProtocol" class="condition-list">
            <article v-for="condition in currentProtocol.required_gates" :key="condition.value" :class="{ complete: currentProtocol.approved_gates.includes(condition.value) }">
              <span>{{ currentProtocol.approved_gates.includes(condition.value) ? '✓' : '待' }}</span>
              <div><strong>{{ friendlyCondition(condition.value, condition.label) }}</strong><small>{{ currentProtocol.approved_gates.includes(condition.value) ? '已完成核对' : '完成后才能开始实施' }}</small></div>
            </article>
          </div>

          <details v-if="currentProtocol" class="technical-records">
            <summary>查看研究技术记录</summary>
            <dl>
              <div><dt>方案登记</dt><dd>第 {{ currentProtocol.version_no }} 版 · {{ currentProtocol.registered_at }}</dd></div>
              <div><dt>伦理审查记录</dt><dd>{{ currentProtocol.ethics_approval_ref || '未登记' }}</dd></div>
              <div><dt>预先登记记录</dt><dd>{{ currentProtocol.preregistration_ref || '未登记' }}</dd></div>
              <div><dt>方案校验值</dt><dd>{{ currentProtocol.content_hash }}</dd></div>
            </dl>
          </details>
        </section>

        <section v-else-if="activeTab === 'classes'" class="workspace-section">
          <header class="section-heading">
            <div><h3>实验班与对照班安排</h3><p>先确定共同前测，再按照已确认的方法安排班级。安排完成后仍需检查两类班级的起点情况是否可比。</p></div>
            <button class="primary-button" type="button" :disabled="!protocolReady" @click="openClassModal">安排一个班级</button>
          </header>
          <div v-if="currentProtocol?.cohort_assignments?.length" class="responsive-table">
            <table><thead><tr><th>班级</th><th>实验中的安排</th><th>安排方法</th><th>记录编号</th></tr></thead><tbody>
              <tr v-for="row in currentProtocol.cohort_assignments" :key="row.id"><td>{{ row.class_group_name }}</td><td>{{ friendlyArm(row.arm) }}</td><td>{{ friendlyMethod(row.allocation_method) }}</td><td>{{ row.allocation_unit_code }}</td></tr>
            </tbody></table>
          </div>
          <div v-else class="guided-empty compact"><strong>尚未安排实验班和对照班</strong><p>请先确认实验方案。正式开展班级对照实验时，应同时有实验班与对照班，并记录实际进入了哪一种教学安排。</p></div>
        </section>

        <section v-else-if="activeTab === 'implementation'" class="workspace-section">
          <header class="section-heading">
            <div><h3>教学实施与实际情况</h3><p>记录计划时间、实际开始与结束，以及是否按方案实施。设备、缺课或教学条件变化应单独记录，不能当作学生低表现。</p></div>
            <button class="primary-button" type="button" :disabled="!protocolReady" @click="openRunModal">制定实施计划</button>
          </header>
          <div v-if="currentProtocol?.runs?.length" class="run-list">
            <article v-for="run in currentProtocol.runs" :key="run.id">
              <header><div><span>{{ run.run_code }}</span><strong>{{ friendlyStage(currentProtocol.stage) }}</strong></div><span class="state-pill" :class="statusTone(run.status)">{{ run.status_label }}</span></header>
              <p>计划时间：{{ run.planned_start || '待定' }} 至 {{ run.planned_end || '待定' }}</p>
              <div class="run-actions">
                <button v-if="run.status === 'planned'" type="button" :disabled="saving" @click="changeRun(run, 'activate')">完成条件检查并开始</button>
                <button v-if="run.status === 'active' || run.status === 'paused'" type="button" :disabled="saving" @click="changeRun(run, 'close')">结束本次实施</button>
                <button v-if="run.status === 'closed'" type="button" :disabled="saving" @click="openLockModal(run)">确认分析数据范围</button>
                <span v-if="run.data_lock">已确认 {{ run.data_lock.row_count }} 条分析记录</span>
              </div>
            </article>
          </div>
          <div v-else class="guided-empty compact"><strong>尚未制定实施计划</strong><p>建立计划不会自动改变学生的评价、动态分层或动态分组结果；学校管理员确认全部开展条件后才可开始。</p></div>
        </section>

        <section v-else class="workspace-section">
          <header class="section-heading">
            <div><h3>后测、问卷与分析准备</h3><p>只比较事先确定的主要观察指标，并保留缺测、退出、设备问题和未获得机会等情况。</p></div>
          </header>
          <div class="analysis-grid">
            <article><span>共同前测</span><strong>{{ currentProtocol ? '已写入实验方案' : '待确定' }}</strong><p>{{ protocolText('inclusion_criteria') || '两类班级应使用一致的学习起点诊断。' }}</p></article>
            <article><span>共同后测或问卷</span><strong>{{ protocolList('primary_outcomes').length ? protocolList('primary_outcomes').length + ' 项观察内容' : '待确定' }}</strong><p>{{ protocolText('primary_outcomes') || '可以使用测试、表现任务、作品评价或问卷。' }}</p></article>
            <article><span>缺失材料处理</span><strong>{{ protocolText('missing_data_plan') ? '已说明' : '待说明' }}</strong><p>{{ protocolText('missing_data_plan') || '缺测、设备问题或未获得机会不能补成低分。' }}</p></article>
            <article><span>分析数据</span><strong>{{ lockedRunCount ? lockedRunCount + ' 份已确认' : '尚未确认' }}</strong><p>实施结束并完成共同后测或问卷后，再确认用于分析的数据范围。</p></article>
          </div>
          <a v-if="currentProtocol" class="secondary-button export-link" :href="researchProtocolExportUrl(currentProtocol.id)">导出分析数据说明与变量表</a>
          <p class="analysis-boundary">平台提供数据整理和 SPSS 分析准备，不会自动把统计差异写成教育效果结论。结果解释还需要结合实验设计、实施偏离、样本量和学生权益记录。</p>
        </section>
      </main>

      <main v-else class="experiment-workspace workspace-loading">{{ loading ? '正在加载教育实验信息…' : '从左侧建立一项教育实验开始。' }}</main>
    </section>

    <div v-if="modal" class="modal-backdrop" @click.self="closeModal">
      <section v-if="modal === 'study'" v-modal-focus="closeModal" class="entity-modal experiment-modal" role="dialog" aria-modal="true" aria-labelledby="study-modal-title">
        <header class="modal-header"><div><h2 id="study-modal-title">建立教育实验草稿</h2><p>先记录实验目的和适用课程，不会立即安排学生或班级。</p></div><button class="icon-button" type="button" aria-label="关闭" :disabled="saving" @click="closeModal">×</button></header>
        <form class="experiment-form" @submit.prevent="saveStudy">
          <label>实验编号<input v-model.trim="studyForm.code" required maxlength="64" placeholder="例如 IT-2026-01"></label>
          <label>实验名称<input v-model.trim="studyForm.title" required maxlength="200" placeholder="例如 信息科技项目式学习班级对照实验"></label>
          <label>学科<select v-model="studyForm.subject_id"><option value="">不限定学科</option><option v-for="row in options?.subjects" :key="row.id" :value="row.id">{{ row.name }}</option></select></label>
          <label>课程<select v-model="studyForm.course_id"><option value="">不限定课程</option><option v-for="row in options?.courses" :key="row.id" :value="row.id">{{ row.title }}</option></select></label>
          <label class="span-2">希望回答的教育问题<textarea v-model.trim="studyForm.description" required rows="4" placeholder="例如：在共同前测基础上，项目式学习是否有助于学生在数据处理与问题解决任务中形成更完整的学习表现？"></textarea></label>
          <footer class="span-2"><button type="button" class="secondary-button" :disabled="saving" @click="closeModal">取消</button><button type="submit" class="primary-button" :disabled="saving">{{ saving ? '保存中…' : '保存草稿' }}</button></footer>
        </form>
      </section>

      <section v-else-if="modal === 'protocol'" v-modal-focus="closeModal" class="entity-modal experiment-modal wide" role="dialog" aria-modal="true" aria-labelledby="protocol-modal-title">
        <header class="modal-header"><div><h2 id="protocol-modal-title">完善教育实验方案</h2><p>确认后保留当前版本；需要调整时登记新版本，已有结果不会被覆盖。</p></div><button class="icon-button" type="button" aria-label="关闭" :disabled="saving" @click="closeModal">×</button></header>
        <form class="experiment-form protocol-form" @submit.prevent="saveProtocol">
          <h3 class="span-2">一、实验问题与共同测量</h3>
          <label>实验类型<select v-model="protocolForm.stage" required @change="updateStage"><option v-for="row in stageChoices" :key="row.value" :value="row.value">{{ row.label }}</option></select></label>
          <label>需要比较的内容（每行一项）<textarea v-model="protocolForm.estimands" required rows="3" placeholder="例如：实验班与对照班在后测项目任务表现上的差异"></textarea></label>
          <label>希望回答的问题（每行一项）<textarea v-model="protocolForm.research_questions" required rows="3"></textarea></label>
          <label>共同前测、后测或问卷的主要观察内容（每行一项）<textarea v-model="protocolForm.primary_outcomes" required rows="3"></textarea></label>
          <label>同时观察的学生权益与实施影响（每行一项）<textarea v-model="protocolForm.safety_outcomes" required rows="3" placeholder="例如：学习机会、额外负担、退出情况"></textarea></label>
          <label>参与范围（每行一项）<textarea v-model="protocolForm.inclusion_criteria" required rows="3"></textarea></label>
          <label>不纳入分析的情形（每行一项）<textarea v-model="protocolForm.exclusion_criteria" required rows="3"></textarea></label>
          <label>缺测、设备问题与未获得机会如何处理<textarea v-model="protocolForm.missing_data_plan" required rows="3"></textarea></label>
          <label>准备采用的分析方法<textarea v-model="protocolForm.analysis_plan" required rows="3"></textarea></label>
          <label>需要暂停或终止实验的情形<textarea v-model="protocolForm.stopping_rules" required rows="3"></textarea></label>
          <label>结果可以解释到什么范围<textarea v-model="protocolForm.claim_boundary" required rows="3"></textarea></label>

          <h3 class="span-2">二、学生权益与研究登记</h3>
          <label>伦理审查编号<input v-model="protocolForm.ethics_approval_ref" :required="protocolForm.stage !== 'E2'"></label>
          <label>伦理审查日期<input v-model="protocolForm.ethics_approved_at" type="date" :required="protocolForm.stage !== 'E2'"></label>
          <label>实验方案预先登记编号或地址<input v-model="protocolForm.preregistration_ref" :required="protocolForm.stage !== 'E1'"></label>
          <label>预先登记时间<input v-model="protocolForm.preregistered_at" type="datetime-local" :required="protocolForm.stage !== 'E1'"></label>
          <label class="span-2">知情、退出与未成年人保护安排<textarea v-model="protocolForm.consent_plan" required rows="3"></textarea></label>

          <template v-if="['E4','E5','E6'].includes(protocolForm.stage)">
            <h3 class="span-2">三、确认本次实际使用的教学与评价方案</h3>
            <label>评价方案与评价标准版本<input v-model="protocolForm.evaluation_policy" required placeholder="填写平台中的方案名称与版本"></label>
            <label>动态分层规则版本<input v-model="protocolForm.content_band_policy" required placeholder="填写本次使用的规则名称与版本"></label>
            <label>动态分组规则版本<input v-model="protocolForm.grouping_policy" required placeholder="填写本次使用的规则名称与版本"></label>
          </template>
          <footer class="span-2"><button type="button" class="secondary-button" :disabled="saving" @click="closeModal">取消</button><button type="submit" class="primary-button" :disabled="saving">{{ saving ? '确认中…' : '确认并保存方案版本' }}</button></footer>
        </form>
      </section>

      <section v-else-if="modal === 'condition'" v-modal-focus="closeModal" class="entity-modal experiment-modal" role="dialog" aria-modal="true" aria-labelledby="condition-modal-title">
        <header class="modal-header"><div><h2 id="condition-modal-title">记录开展条件</h2><p>每一项都应引用学校真实的审查、培训或检查记录。</p></div><button class="icon-button" type="button" aria-label="关闭" :disabled="saving" @click="closeModal">×</button></header>
        <form class="experiment-form" @submit.prevent="saveCondition">
          <label>核对项目<select v-model="conditionForm.gate" required><option value="" disabled>请选择</option><option v-for="row in currentProtocol?.required_gates" :key="row.value" :value="row.value">{{ friendlyCondition(row.value, row.label) }}</option></select></label>
          <label>核对结论<select v-model="conditionForm.decision" required><option v-for="row in options?.gate_decisions" :key="row.value" :value="row.value">{{ row.label }}</option></select></label>
          <label class="span-2">材料编号或保存位置<input v-model="conditionForm.evidence_ref" required maxlength="255"></label>
          <label class="span-2">情况说明<textarea v-model="conditionForm.note" rows="3"></textarea></label>
          <footer class="span-2"><button type="button" class="secondary-button" :disabled="saving" @click="closeModal">取消</button><button type="submit" class="primary-button" :disabled="saving">{{ saving ? '保存中…' : '保存核对结果' }}</button></footer>
        </form>
      </section>

      <section v-else-if="modal === 'class'" v-modal-focus="closeModal" class="entity-modal experiment-modal" role="dialog" aria-modal="true" aria-labelledby="class-modal-title">
        <header class="modal-header"><div><h2 id="class-modal-title">安排实验班或对照班</h2><p>实验开始后不能直接更换班级；如有变化，应另行记录实施偏离。</p></div><button class="icon-button" type="button" aria-label="关闭" :disabled="saving" @click="closeModal">×</button></header>
        <form class="experiment-form" @submit.prevent="saveClass">
          <label>班级<select v-model="classForm.class_group_id" required><option value="" disabled>请选择</option><option v-for="row in options?.classes" :key="row.id" :value="row.id">{{ row.grade }} · {{ row.name }}</option></select></label>
          <label>实验中的安排<select v-model="classForm.arm" required><option value="experiment">实验班</option><option value="control">对照班</option><option value="observational">观察班</option><option value="external_confirmation">外校复核班</option></select></label>
          <label>安排方法<select v-model="classForm.allocation_method" required><option v-for="row in options?.allocation_methods" :key="row.value" :value="row.value">{{ friendlyMethod(row.value) }}</option></select></label>
          <label>安排记录编号<input v-model="classForm.allocation_unit_code" required maxlength="96"></label>
          <label class="check-label"><input v-model="classForm.development_site" type="checkbox">该班级参与过方案开发</label>
          <label class="check-label"><input v-model="classForm.prior_policy_access" type="checkbox">该班级此前接触过本次实验方案</label>
          <footer class="span-2"><button type="button" class="secondary-button" :disabled="saving" @click="closeModal">取消</button><button type="submit" class="primary-button" :disabled="saving">{{ saving ? '保存中…' : '确认班级安排' }}</button></footer>
        </form>
      </section>

      <section v-else-if="modal === 'run'" v-modal-focus="closeModal" class="entity-modal experiment-modal" role="dialog" aria-modal="true" aria-labelledby="run-modal-title">
        <header class="modal-header"><div><h2 id="run-modal-title">制定教育实验实施计划</h2><p>完成全部开展条件后，才能正式开始。</p></div><button class="icon-button" type="button" aria-label="关闭" :disabled="saving" @click="closeModal">×</button></header>
        <form class="experiment-form" @submit.prevent="saveRun">
          <label>本次实施编号<input v-model="runForm.run_code" required maxlength="96"></label>
          <label>计划开始时间<input v-model="runForm.planned_start" type="datetime-local"></label>
          <label>计划结束时间<input v-model="runForm.planned_end" type="datetime-local"></label>
          <p class="form-callout span-2">系统不会因为建立实施计划而自动改变学生的评价、动态分层或动态分组结果。</p>
          <footer class="span-2"><button type="button" class="secondary-button" :disabled="saving" @click="closeModal">取消</button><button type="submit" class="primary-button" :disabled="saving">{{ saving ? '保存中…' : '保存实施计划' }}</button></footer>
        </form>
      </section>

      <section v-else v-modal-focus="closeModal" class="entity-modal experiment-modal wide" role="dialog" aria-modal="true" aria-labelledby="lock-modal-title">
        <header class="modal-header"><div><h2 id="lock-modal-title">确认用于分析的数据范围</h2><p>确认后不能覆盖；如需修正，应保留本次记录并另建数据版本。</p></div><button class="icon-button" type="button" aria-label="关闭" :disabled="saving" @click="closeModal">×</button></header>
        <form class="experiment-form" @submit.prevent="saveDataLock">
          <label>分析判断时点<input v-model="lockForm.decision_as_of" type="datetime-local" required></label>
          <label>数据收集截止时间<input v-model="lockForm.data_cutoff" type="datetime-local" required></label>
          <label>记录数量<input v-model.number="lockForm.row_count" type="number" min="0" required></label>
          <label>数据文件校验值<input v-model.trim="lockForm.dataset_hash" required minlength="64" maxlength="64"><small>由系统或数据整理工具生成，用于确认文件没有被替换。</small></label>
          <label>数据文件（每行一个）<textarea v-model="lockForm.data_files" required rows="5" placeholder="共同前测成绩表&#10;共同后测成绩表&#10;学生问卷"></textarea></label>
          <label>分析变量（每行一个）<textarea v-model="lockForm.variables" required rows="5" placeholder="班级实验安排&#10;共同前测成绩&#10;共同后测成绩"></textarea></label>
          <label>缺失材料情况<textarea v-model="lockForm.missingness_note" rows="4" placeholder="说明缺测、设备问题、请假或未获得机会等情况"></textarea></label>
          <label>未纳入分析的情况<textarea v-model="lockForm.exclusion_note" rows="4" placeholder="说明人数、原因及其与预先方案是否一致"></textarea></label>
          <footer class="span-2"><button type="button" class="secondary-button" :disabled="saving" @click="closeModal">取消</button><button type="submit" class="primary-button" :disabled="saving">{{ saving ? '确认中…' : '确认分析数据范围' }}</button></footer>
        </form>
      </section>
    </div>
  </AppShell>
</template>

<style scoped>
.experiment-intro {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  border: 1px solid #cfe0f5;
  border-radius: 10px;
  padding: 22px 24px;
  background: linear-gradient(135deg, #f6fbff, #fff 72%);
}

.experiment-intro span,
.workspace-heading > div > span {
  color: var(--primary);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: .05em;
}

.experiment-intro h2 {
  max-width: 820px;
  margin: 5px 0 8px;
  font-size: clamp(21px, 2.2vw, 30px);
  line-height: 1.35;
}

.experiment-intro p,
.workspace-heading p,
.section-heading p,
.guided-empty p,
.analysis-grid p {
  margin: 0;
  color: var(--muted);
  line-height: 1.65;
}

.experiment-steps {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 1px;
  margin: 16px 0;
  border: 1px solid var(--line);
  border-radius: 9px;
  padding: 0;
  overflow: hidden;
  background: var(--line);
  list-style: none;
}

.experiment-steps li {
  min-width: 0;
  display: flex;
  gap: 9px;
  padding: 13px 12px;
  background: #fff;
}

.experiment-steps li > span {
  flex: 0 0 26px;
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: #eef2f7;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
}

.experiment-steps li.done > span {
  background: #e4f6eb;
  color: #166534;
}

.experiment-steps strong,
.experiment-steps small {
  display: block;
}

.experiment-steps strong {
  font-size: 13px;
}

.experiment-steps small {
  margin-top: 4px;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.4;
}

.experiment-layout {
  min-height: 540px;
  display: grid;
  grid-template-columns: 270px minmax(0, 1fr);
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  background: #fff;
  box-shadow: 0 12px 28px rgba(15, 23, 42, .04);
}

.experiment-list {
  border-right: 1px solid var(--line);
  background: #f8fafc;
}

.experiment-list > header {
  display: flex;
  justify-content: space-between;
  padding: 18px;
  border-bottom: 1px solid var(--line);
}

.experiment-list > button {
  width: 100%;
  display: grid;
  gap: 5px;
  border: 0;
  border-bottom: 1px solid var(--line);
  padding: 15px 18px;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.experiment-list > button.active {
  border-left: 4px solid var(--primary);
  padding-left: 14px;
  background: #fff;
}

.experiment-list button span,
.experiment-list button small {
  color: var(--muted);
}

.list-empty {
  display: grid;
  gap: 10px;
  padding: 24px 18px;
  color: var(--muted);
  text-align: center;
}

.list-empty p {
  margin: 0;
  line-height: 1.6;
}

.experiment-workspace {
  min-width: 0;
}

.workspace-heading,
.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
}

.workspace-heading {
  padding: 20px 22px;
  border-bottom: 1px solid var(--line);
}

.workspace-heading h2,
.section-heading h3 {
  margin: 4px 0 6px;
}

.experiment-tabs {
  display: flex;
  border-bottom: 1px solid var(--line);
  background: #f8fafc;
}

.experiment-tabs button {
  min-height: 48px;
  border: 0;
  border-bottom: 3px solid transparent;
  padding: 0 20px;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
}

.experiment-tabs button.active {
  border-bottom-color: var(--primary);
  background: #fff;
  color: var(--primary-dark);
  font-weight: 700;
}

.workspace-section {
  display: grid;
  gap: 18px;
  padding: 22px;
}

.design-grid,
.analysis-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.design-grid article,
.analysis-grid article {
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 16px;
  background: #fbfdff;
}

.design-grid article > span,
.analysis-grid article > span {
  display: block;
  margin-bottom: 7px;
  color: var(--muted);
  font-size: 12px;
}

.design-grid ul {
  margin: 5px 0 0;
  padding-left: 20px;
  line-height: 1.65;
}

.design-grid small {
  display: block;
  margin-top: 5px;
  color: var(--muted);
}

.guided-empty {
  display: grid;
  justify-items: start;
  gap: 10px;
  border: 1px dashed #a9c4e5;
  border-radius: 9px;
  padding: 28px;
  background: #f7fbff;
}

.guided-empty.compact {
  min-height: 180px;
  align-content: center;
  justify-items: center;
  text-align: center;
}

.condition-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.condition-list article {
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
}

.condition-list article > span {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: #fff4dd;
  color: #9a4f08;
  font-size: 12px;
  font-weight: 700;
}

.condition-list article.complete > span {
  background: #e4f6eb;
  color: #166534;
}

.condition-list strong,
.condition-list small {
  display: block;
}

.condition-list small {
  margin-top: 3px;
  color: var(--muted);
}

.technical-records {
  border-top: 1px solid var(--line);
  padding-top: 14px;
}

.technical-records summary {
  color: var(--primary-dark);
  cursor: pointer;
  font-weight: 600;
}

.technical-records dl {
  display: grid;
  gap: 8px;
}

.technical-records dl div {
  display: grid;
  grid-template-columns: 130px minmax(0, 1fr);
  gap: 12px;
}

.technical-records dt {
  color: var(--muted);
}

.technical-records dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.responsive-table {
  overflow: auto;
}

.responsive-table table {
  min-width: 720px;
}

.run-list {
  display: grid;
  gap: 12px;
}

.run-list article {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 15px;
}

.run-list article > header,
.run-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.run-list header span,
.run-list header strong {
  display: block;
}

.run-list p {
  color: var(--muted);
}

.run-actions {
  justify-content: flex-start;
}

.run-actions button {
  min-height: 38px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 0 12px;
  background: #fff;
  color: var(--primary-dark);
  cursor: pointer;
}

.state-pill {
  border-radius: 999px;
  padding: 5px 9px;
  background: #fff4dd;
  color: #9a4f08;
  font-size: 12px;
}

.state-pill.success { background: #e4f6eb; color: #166534; }
.state-pill.info { background: #e8f1ff; color: #24527a; }
.state-pill.danger { background: #fff0f0; color: #b42318; }

.analysis-grid strong {
  display: block;
  margin-bottom: 8px;
}

.export-link {
  width: fit-content;
  text-decoration: none;
}

.analysis-boundary,
.form-callout {
  margin: 0;
  border-left: 4px solid #d97706;
  padding: 11px 13px;
  background: #fffaf0;
  color: #7c4a03;
  line-height: 1.6;
}

.workspace-loading {
  display: grid;
  place-items: center;
  color: var(--muted);
}

.experiment-modal {
  width: min(760px, calc(100vw - 32px));
  max-height: min(88vh, 900px);
  overflow: auto;
}

.experiment-modal.wide {
  width: min(1040px, calc(100vw - 32px));
}

.experiment-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  padding: 20px 22px;
}

.experiment-form label {
  min-width: 0;
  display: grid;
  gap: 6px;
  color: #334155;
  font-size: 13px;
  font-weight: 600;
}

.experiment-form input,
.experiment-form select,
.experiment-form textarea {
  width: 100%;
  min-height: 42px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 9px 10px;
  background: #fff;
  color: var(--text);
  font: inherit;
  font-weight: 400;
}

.experiment-form textarea {
  resize: vertical;
}

.experiment-form h3 {
  margin: 8px 0 0;
  border-bottom: 1px solid var(--line);
  padding-bottom: 8px;
  font-size: 16px;
}

.experiment-form .span-2 {
  grid-column: 1 / -1;
}

.experiment-form .check-label {
  display: flex;
  align-items: center;
  gap: 8px;
}

.experiment-form .check-label input {
  width: 18px;
  min-height: 18px;
}

.experiment-form label small {
  color: var(--muted);
  font-weight: 400;
}

.experiment-form footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 4px;
}

@media (max-width: 1100px) {
  .experiment-steps { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}

@media (max-width: 760px) {
  .experiment-intro,
  .workspace-heading,
  .section-heading { flex-direction: column; }

  .experiment-intro .primary-button,
  .workspace-heading .secondary-button,
  .section-heading .primary-button { width: 100%; }

  .experiment-steps { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .experiment-layout { grid-template-columns: 1fr; }
  .experiment-list { border-right: 0; border-bottom: 1px solid var(--line); }
  .experiment-tabs { overflow-x: auto; }
  .experiment-tabs button { flex: 0 0 auto; }
  .design-grid,
  .analysis-grid,
  .condition-list,
  .experiment-form { grid-template-columns: 1fr; }
  .experiment-form .span-2 { grid-column: auto; }
}
</style>
