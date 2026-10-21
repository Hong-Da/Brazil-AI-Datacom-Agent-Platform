import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './styles/app.css'
import './styles/m2.css'
import './styles/m3.css'
import './styles/m4.css'
import './styles/m5.css'
import './styles/m6.css'
import './styles/m9.css'
import './styles/m98.css'
import './styles/tokens.css'
import App from './App.vue'
import { router } from './router'
import { i18n } from './i18n'

const app = createApp(App).use(createPinia()).use(i18n).use(router).use(ElementPlus)
// 第一次导航（守卫里查是否已配置、是否登录）完成后再挂载：否则会先闪过主界面再跳到登录页（REQ-048）
router.isReady().catch(() => undefined).then(() => app.mount('#app'))
