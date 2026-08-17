/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: '#84cc16', light: '#a3e635', dark: '#65a30d' },
        success: '#22c55e',
        danger: '#ef4444',
        warning: '#f59e0b',
        surface: { DEFAULT: '#1e293b', light: '#334155', dark: '#0f172a' },
      },
    },
  },
  plugins: [],
}
