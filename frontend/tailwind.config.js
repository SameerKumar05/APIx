/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#f0f7ff',
          100: '#e0effe',
          200: '#b9ddfd',
          300: '#7cc2fc',
          400: '#36a3f8',
          500: '#0c87eb',
          600: '#006bc9',
          700: '#0155a3',
          800: '#064986',
          900: '#0b3e6f',
          950: '#072749',
        },
      },
    },
  },
  plugins: [],
}
