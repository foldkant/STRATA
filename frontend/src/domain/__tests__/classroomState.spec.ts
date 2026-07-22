import { describe, expect, it } from 'vitest'
import { classroomControlState } from '../classroomState'

describe('teacher classroom state controls', () => {
  it('allows a draft classroom to start and publish its selected step', () => {
    const state = classroomControlState({ sessionStatus: 'draft', stepStatus: 'idle', hasSelectedStep: true, hasCurrentStep: false, stepCount: 3, currentStepIndex: -1 })
    expect(state).toMatchObject({ canStart: true, canFinish: false, canPublishStep: true, canRunCommands: false })
  })

  it('allows locking and advancing an open running step', () => {
    const state = classroomControlState({ sessionStatus: 'running', stepStatus: 'open', hasSelectedStep: true, hasCurrentStep: true, stepCount: 3, currentStepIndex: 0 })
    expect(state).toMatchObject({ canFinish: true, canRunCommands: true, canLockStep: true, canCloseStep: true, canPublishNextStep: true })
  })

  it('disables publication after the classroom finishes', () => {
    const state = classroomControlState({ sessionStatus: 'finished', stepStatus: 'closed', hasSelectedStep: true, hasCurrentStep: true, stepCount: 3, currentStepIndex: 2 })
    expect(state).toMatchObject({ canRestart: true, canPublishStep: false, canPublishNextStep: false, canCloseStep: false })
  })
})
