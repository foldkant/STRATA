import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import AppSelect from './components/AppSelect.vue'
import { router } from './router'
import './styles/main.css'
import './styles/interaction-foundations.css'
import './styles/navigation-shell.css'

const app = createApp(App)

app.config.errorHandler = (error) => {
  console.error('页面运行异常', error)
  if (router.currentRoute.value.path !== '/500') {
    void router.replace('/500')
  }
}

app
  .component('AppSelect', AppSelect)
  .use(createPinia())
  .use(router)
  .mount('#app')
