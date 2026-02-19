/** @type {import('tailwindcss').Config} */
export default {
    content: [
        "./index.html",
        "./src/**/*.{js,ts,jsx,tsx}",
    ],
    theme: {
        extend: {
            fontFamily: {
                sans: ['"Inter"', 'sans-serif'],
            },
            colors: {
                colors: {
                    // primary: Removed to enforce monochrome/zinc usage
                }
            }
        },
    },
    plugins: [],
}
