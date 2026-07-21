import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import AppSelect from './components/AppSelect.vue'
import { router } from './router'
import './styles/main.css'

createApp(App)
  .component('AppSelect', AppSelect)
  .use(createPinia())
  .use(router)
  .mount('#app')
