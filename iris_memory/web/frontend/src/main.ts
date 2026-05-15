import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createVuetify } from 'vuetify'
import 'vuetify/styles'

import { mdi } from 'vuetify/iconsets/mdi-svg'

import * as customIcons from './icons'
import App from './App.vue'
import router from './router'

const svgAliases: Record<string, string> = {}
for (const [key, value] of Object.entries(customIcons)) {
  svgAliases[key] = `svg:${value}`
}

const vuetify = createVuetify({
  icons: {
    defaultSet: 'mdi',
    sets: {
      mdi: {
        ...mdi,
        aliases: {
          ...mdi.aliases,
          ...svgAliases
        }
      }
    }
  },
  theme: {
    defaultTheme: 'dark',
    themes: {
      dark: {
        colors: {
          primary: '#7C4DFF',
          secondary: '#00BFA5',
          accent: '#FF4081',
          background: '#121212',
          surface: '#1E1E1E',
          error: '#CF6679',
          warning: '#FFB300',
          info: '#2196F3',
          success: '#4CAF50'
        }
      },
      light: {
        colors: {
          primary: '#7C4DFF',
          secondary: '#00BFA5',
          accent: '#FF4081',
          background: '#FAFAFA',
          surface: '#FFFFFF',
          error: '#B00020',
          warning: '#FFB300',
          info: '#2196F3',
          success: '#4CAF50'
        }
      }
    }
  }
})

const pinia = createPinia()
const app = createApp(App)

app.use(pinia)
app.use(router)
app.use(vuetify)

app.mount('#app')
