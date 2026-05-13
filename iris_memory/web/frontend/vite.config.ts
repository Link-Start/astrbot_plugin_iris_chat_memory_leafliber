import { defineConfig, Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import vuetify from 'vite-plugin-vuetify'
import { resolve } from 'path'

function removeCrossorigin(): Plugin {
  return {
    name: 'remove-crossorigin',
    enforce: 'post',
    generateBundle(_, bundle) {
      for (const [fileName, chunk] of Object.entries(bundle)) {
        if (fileName.endsWith('.html') && chunk.type === 'asset') {
          chunk.source = (chunk.source as string)
            .replace(/\s+crossorigin/g, '')
            .replace(/<link[^>]*rel="modulepreload"[^>]*>/g, '')
        }
      }
    }
  }
}

export default defineConfig({
  plugins: [
    vue(),
    vuetify({ autoImport: true }),
    removeCrossorigin()
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src')
    }
  },
  base: './',
  build: {
    outDir: resolve(__dirname, '../../../pages/iris'),
    emptyOutDir: true,
    assetsDir: 'assets',
    sourcemap: false,
    chunkSizeWarningLimit: 1000,
    modulePreload: false,
    cssCodeSplit: false,
    rollupOptions: {
      output: {
        manualChunks: {
          'vue-vendor': ['vue', 'vue-router', 'pinia'],
          'vuetify': ['vuetify']
        }
      }
    }
  }
})
