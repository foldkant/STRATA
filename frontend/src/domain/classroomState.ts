export type ClassroomSessionStatus = 'draft' | 'running' | 'finished'
export type ClassroomStepStatus = 'idle' | 'open' | 'locked' | 'closed'

export type ClassroomControlState = {
  canStart: boolean
  canFinish: boolean
  canRestart: boolean
  canRunCommands: boolean
  canPublishStep: boolean
  canLockStep: boolean
  canCloseStep: boolean
  canPublishNextStep: boolean
}

export function classroomControlState(input: {
  sessionStatus: ClassroomSessionStatus
  stepStatus: ClassroomStepStatus
  hasSelectedStep: boolean
  hasCurrentStep: boolean
  stepCount: number
  currentStepIndex: number
}): ClassroomControlState {
  const finished = input.sessionStatus === 'finished'
  return {
    canStart: input.sessionStatus === 'draft',
    canFinish: input.sessionStatus === 'running',
    canRestart: finished,
    canRunCommands: input.sessionStatus === 'running',
    canPublishStep: input.hasSelectedStep && !finished,
    canLockStep: input.stepStatus === 'open',
    canCloseStep: input.hasCurrentStep && input.stepStatus !== 'closed',
    canPublishNextStep: !finished && input.stepCount > 0 && input.currentStepIndex < input.stepCount - 1
  }
}
