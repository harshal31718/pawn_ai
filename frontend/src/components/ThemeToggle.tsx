import type { ReactNode } from 'react'

export type Theme = 'system' | 'light' | 'dark'

interface ThemeToggleProps {
  theme: Theme
  onChangeTheme: (t: Theme) => void
  variant?: 'compact' | 'detailed'
}

interface ThemeOption {
  value: Theme
  label: string
  icon: ReactNode
}

export default function ThemeToggle({ theme, onChangeTheme, variant = 'compact' }: ThemeToggleProps) {
  const options: ThemeOption[] = [
    {
      value: 'light',
      label: 'Light',
      icon: (
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-3.5 h-3.5 transition-transform duration-300 group-hover:rotate-45">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v2.25m0 13.5V21M5.03 5.03l1.59 1.59m10.76 10.76l1.59 1.59M3 12h2.25m13.5 0H21M5.03 18.97l1.59-1.59m10.76-10.76l1.59-1.59M12 9a3 3 0 100 6 3 3 0 000-6z" />
        </svg>
      )
    },
    {
      value: 'system',
      label: 'System',
      icon: (
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-3.5 h-3.5 transition-transform duration-300 group-hover:scale-110">
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 17.25v1.007a3 3 0 01-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0115 18.257V17.25m6-12V15a2.25 2.25 0 01-2.25 2.25H5.25A2.25 2.25 0 013 15V5.25m18 0A2.25 2.25 0 0018.75 3H5.25A2.25 2.25 0 003 5.25m18 0V12a2.25 2.25 0 01-2.25 2.25H5.25A2.25 2.25 0 013 12V5.25" />
        </svg>
      )
    },
    {
      value: 'dark',
      label: 'Dark',
      icon: (
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-3.5 h-3.5 transition-transform duration-300 group-hover:-rotate-12">
          <path strokeLinecap="round" strokeLinejoin="round" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" />
        </svg>
      )
    }
  ]

  const activeIndex = options.findIndex((opt) => opt.value === theme)

  if (variant === 'detailed') {
    return (
      <div className="relative flex items-center bg-theme-bg/60 backdrop-blur-md border border-theme-border/60 rounded-xl p-1 gap-1 select-none pointer-events-auto w-full">
        {/* Sliding background */}
        <div
          className="absolute top-1 bottom-1 left-1 rounded-lg bg-theme-surface border border-theme-border/50 shadow-sm transition-all duration-300 [transition-timing-function:cubic-bezier(0.175,0.885,0.32,1.275)]"
          style={{
            width: 'calc((100% - 16px) / 3)',
            transform: `translateX(calc(${activeIndex * 100}% + ${activeIndex * 4}px))`,
          }}
        />
        {options.map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChangeTheme(opt.value)}
            title={opt.label}
            className={`group relative z-10 flex-1 py-1.5 px-3 md:px-1.5 xl:px-3 flex items-center justify-center gap-1.5 rounded-lg text-xs font-medium transition-colors duration-200 focus:outline-none cursor-pointer ${
              theme === opt.value
                ? 'text-theme-text'
                : 'text-theme-text-muted hover:text-theme-text'
            }`}
          >
            {opt.icon}
            <span className="inline md:hidden xl:inline">{opt.label}</span>
          </button>
        ))}
      </div>
    )
  }

  return (
    <div className="relative flex items-center bg-theme-surface/75 backdrop-blur-md border border-theme-border/40 rounded-full p-0.5 shadow-md pointer-events-auto select-none">
      {/* Sliding background */}
      <div
        className="absolute top-0.5 bottom-0.5 left-0.5 rounded-full bg-theme-bg border border-theme-border/50 shadow-sm transition-all duration-300 [transition-timing-function:cubic-bezier(0.175,0.885,0.32,1.275)]"
        style={{
          width: '28px',
          transform: `translateX(${activeIndex * 28}px)`,
        }}
      />
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChangeTheme(opt.value)}
          className={`group relative z-10 w-7 h-7 flex items-center justify-center rounded-full transition-colors duration-200 focus:outline-none cursor-pointer ${
            theme === opt.value
              ? 'text-theme-text'
              : 'text-theme-text-muted hover:text-theme-text'
          }`}
          title={`Switch to ${opt.label} mode`}
        >
          {opt.icon}
        </button>
      ))}
    </div>
  )
}
