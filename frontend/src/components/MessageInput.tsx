import { useRef, useState, useEffect, type KeyboardEvent } from 'react'
import ModelSwitcher from './ModelSwitcher'
import type { RegistryModel } from '../api/client'

interface Props {
  value: string
  onChange: (value: string) => void
  onSend: (content: string) => void
  onStop?: () => void
  disabled?: boolean
  onUpload?: (file: File) => void
  isUploading?: boolean
  selectedProvider?: string
  onChangeProvider?: (id: string) => void
  models?: RegistryModel[]
}

export default function MessageInput({
  value,
  onChange,
  onSend,
  onStop,
  disabled = false,
  onUpload,
  isUploading = false,
  selectedProvider = '',
  onChangeProvider,
  models = [],
}: Props) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [isMultiLine, setIsMultiLine] = useState(false)
  const prevDisabledRef = useRef(disabled)

  // When streaming ends with text in the box (i.e. a stopped message was
  // restored), refocus the textarea so the user can resume editing.
  useEffect(() => {
    if (prevDisabledRef.current && !disabled && value.trim()) {
      textareaRef.current?.focus()
    }
    prevDisabledRef.current = disabled
  }, [disabled, value])

  const showSend = value.trim().length > 0 || disabled

  useEffect(() => {
    const textarea = textareaRef.current
    if (textarea) {
      textarea.style.height = 'auto'
      const nextHeight = textarea.scrollHeight
      
      setIsMultiLine((prev) => {
        if (value.trim() === '') return false
        if (nextHeight > 44) return true
        if (nextHeight <= 44 && value.length < 50) return false
        return prev
      })

      if (nextHeight > 138) {
        textarea.style.height = '138px'
        textarea.style.overflowY = 'auto'
      } else {
        textarea.style.height = `${nextHeight}px`
        textarea.style.overflowY = 'hidden'
      }
    }
  }, [value])

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  function submit() {
    const trimmed = value.trim()
    if (!trimmed || disabled || isUploading) return
    onSend(trimmed)
    onChange('')
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    onUpload?.(file)
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  return (
    <div className="w-full relative animate-in fade-in slide-in-from-bottom-2 duration-300">
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileChange}
        accept=".pdf,.txt"
        className="hidden"
        id="file-upload-input"
      />

      {/* Unified Connected Island Input */}
      <div className={`
        w-full bg-theme-surface transition-all duration-300
        flex flex-wrap gap-2
        ${disabled ? 'border border-theme-border/40 opacity-75' : 'border border-theme-border'}
        ${isMultiLine
          ? 'items-end p-3 rounded-3xl shadow-lg'
          : 'items-center px-3 py-1.5 rounded-full shadow-md'}
      `}>
        {/* 1. The Textarea: Always mounted to preserve keyboard focus */}
        <textarea
          ref={textareaRef}
          className={`
            resize-none bg-transparent border-none outline-none text-sm text-theme-text
            focus:outline-none max-h-[138px] disabled:opacity-60 disabled:cursor-not-allowed
            ${isMultiLine 
              ? 'w-full order-1 px-1 min-h-[44px]' 
              : 'flex-1 order-2 py-1.5 min-h-[32px]'}
          `}
          placeholder="Ask anything ..."
          rows={1}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled || isUploading}
        />

        {/* 2. Divider line: Visible only in multi-line mode */}
        <div className={`w-full border-t border-theme-border/10 order-2 my-1 ${isMultiLine ? 'block' : 'hidden'}`} />

        {/* 3. Upload Button */}
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled || isUploading}
          className={`
            rounded-full p-2 text-theme-text-muted hover:text-theme-text hover:bg-theme-bg/50
            disabled:opacity-40 disabled:cursor-not-allowed transition-all
            shrink-0 flex items-center justify-center h-9 w-9 active:scale-95 cursor-pointer
            ${isMultiLine ? 'order-3' : 'order-1'}
          `}
          title="Upload document (.pdf, .txt)"
          id="upload-button"
        >
          {isUploading ? (
            <svg className="animate-spin h-4.5 w-4.5 text-theme-text-muted" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
          ) : (
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-5 h-5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M18.375 12.739l-7.693 7.693a4.5 4.5 0 01-6.364-6.364l10.94-10.94A3 3 0 1119.5 7.372L8.552 18.32m.009-.01l-.01.01m5.699-9.941-7.81 7.81a1.5 1.5 0 002.112 2.13" />
            </svg>
          )}
        </button>

        {/* 4. Layout Spacer: Visible only in multi-line mode to push send button right */}
        <div className={`order-4 flex-1 ${isMultiLine ? 'block' : 'hidden'}`} />

        {/* 5. Model Selector — separated from text cluster by a thin border */}
        {selectedProvider && onChangeProvider && models.length > 0 && (
          <div className={`shrink-0 border-l border-theme-border/30 pl-1 transition-all duration-150 ${isMultiLine ? 'order-5' : 'order-3'}`}>
            <ModelSwitcher
              selected={selectedProvider}
              onChange={onChangeProvider}
              disabled={disabled || isUploading}
              models={models}
            />
          </div>
        )}

        {/* 6. Send / Stop Button — animated wrapper slides to make space for model selector */}
        <div className={`
          overflow-hidden transition-all duration-200 shrink-0
          ${isMultiLine ? 'order-6' : 'order-4'}
          ${showSend ? 'max-w-[36px] opacity-100' : 'max-w-0 opacity-0'}
        `}>
          {disabled ? (
            <button
              type="button"
              onClick={() => onStop?.()}
              disabled={!onStop}
              className="relative h-9 w-9 flex items-center justify-center group active:scale-95 cursor-pointer disabled:cursor-default"
              title="Stop generating"
            >
              <svg
                className="absolute inset-0 w-9 h-9 animate-spin"
                viewBox="0 0 36 36"
                fill="none"
                style={{ animationDuration: '900ms' }}
              >
                <circle
                  cx="18" cy="18" r="15"
                  stroke="var(--theme-brand)"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeDasharray="62 32"
                />
              </svg>
              <div className="w-7 h-7 rounded-full bg-theme-user-bubble flex items-center justify-center transition-transform group-hover:scale-105">
                <div className="w-3 h-3 rounded-[3px] bg-theme-user-bubble-text" />
              </div>
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={isUploading || !value.trim()}
              className="
                rounded-full bg-theme-user-bubble text-theme-user-bubble-text h-9 w-9
                disabled:opacity-40 hover:opacity-90 transition-colors duration-150
                flex items-center justify-center active:scale-95 cursor-pointer
              "
              title="Send message"
            >
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.8} stroke="currentColor" className="w-4.5 h-4.5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
              </svg>
            </button>
          )}
        </div>
      </div>

    </div>
  )
}

