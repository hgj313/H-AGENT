import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./hooks/**/*.{ts,tsx}",
    "./services/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // 主色：与 report schema 的 PRD 主色一致
        brand: {
          50: "#eef2fb",
          100: "#dde6f6",
          200: "#b9c8ec",
          300: "#8fa7df",
          400: "#5d80ce",
          500: "#1b2338",
          600: "#161c2d",
          700: "#111722",
          800: "#0c111c",
          900: "#080b15",
        },
        // 节点/事件状态色
        status: {
          pending: "#9ca3af",
          running: "#3b82f6",
          completed: "#10b981",
          error: "#ef4444",
        },
        // 严重等级
        severity: {
          critical: "#dc2626",
          major: "#ea580c",
          minor: "#ca8a04",
          info: "#2563eb",
        },
      },
      fontFamily: {
        sans: [
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "PingFang SC",
          "Microsoft YaHei",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};

export default config;
