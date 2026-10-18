import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './styles/app.css'
import './styles/m2.css'
import './styles/tokens.css'
import App from './App.vue'
import { router } from './router'
import { i18n } from './i18n'

createApp(App).use(createPinia()).use(i18n).use(router).use(ElementPlus).mount('#app')
