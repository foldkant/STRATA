/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}

declare module 'vue' {
  export interface GlobalComponents {
    AppSelect: typeof import('./components/AppSelect.vue')['default']
  }
}

export {}
