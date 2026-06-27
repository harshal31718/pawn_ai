import { useRef, useState, useEffect, type KeyboardEvent } from 'react'

interface Props {
  onSend: (content: string) => void
  disabled?: boolean
  onUpload?: (file: File) => void
  isUploading?: boolean
}

export default function MessageInput({
  onSend,
  disabled = false,
  onUpload,
  isUploading = false,
}: Props) {
  const [value, setValue] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [isMultiLine, setIsMultiLine] = useState(false)

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
    setValue('')
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
        w-full bg-theme-surface border border-theme-border transition-all duration-300
        flex flex-wrap items-end gap-2
        ${isMultiLine 
          ? 'p-3 rounded-3xl shadow-lg' 
          : 'px-3 py-1.5 rounded-full shadow-md'}
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
          placeholder="Hello......."
          rows={1}
          value={value}
          onChange={(e) => setValue(e.target.value)}
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

        {/* 5. Send Button */}
        <button
          type="button"
          onClick={submit}
          disabled={disabled || isUploading || !value.trim()}
          className={`
            rounded-full bg-theme-brand text-theme-brand-text h-9 w-9 shrink-0
            disabled:opacity-40 hover:bg-theme-brand-hover transition-colors
            flex items-center justify-center active:scale-95 cursor-pointer
            ${isMultiLine ? 'order-5' : 'order-3'}
          `}
          title="Send message"
        >
          {disabled ? (
            <svg className="animate-spin h-4.5 w-4.5 text-current" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
          ) : (
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.8} stroke="currentColor" className="w-4.5 h-4.5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
            </svg>
          )}
        </button>
      </div>
    </div>
  )
}

