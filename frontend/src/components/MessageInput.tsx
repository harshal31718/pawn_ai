import { useRef, useState, type KeyboardEvent } from 'react'

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
    <div className="border-t border-zinc-200 px-4 py-3 bg-white shrink-0">
      <div className="flex items-end gap-2">
        <input
          type="file"
          ref={fileInputRef}
          onChange={handleFileChange}
          accept=".pdf,.txt"
          className="hidden"
          id="file-upload-input"
        />
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled || isUploading}
          className="
            rounded-xl border border-zinc-300 p-2 text-zinc-600 hover:bg-zinc-100 
            disabled:opacity-40 disabled:cursor-not-allowed transition-all
            shrink-0 flex items-center justify-center h-10 w-10 active:scale-95
          "
          title="Upload document (.pdf, .txt)"
          id="upload-button"
        >
          {isUploading ? (
            <svg className="animate-spin h-5 w-5 text-zinc-500" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
          ) : (
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-5 h-5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M18.375 12.739l-7.693 7.693a4.5 4.5 0 01-6.364-6.364l10.94-10.94A3 3 0 1119.5 7.372L8.552 18.32m.009-.01l-.01.01m5.699-9.941-7.81 7.81a1.5 1.5 0 002.112 2.13" />
            </svg>
          )}
        </button>

        <textarea
          className="
            flex-1 resize-none rounded-xl border border-zinc-300 px-3 py-2 text-sm 
            focus:outline-none focus:ring-1 focus:ring-zinc-400 min-h-[40px] max-h-40
            disabled:opacity-60 disabled:cursor-not-allowed
          "
          placeholder="Message PAWN… (Enter to send, Shift+Enter for newline)"
          rows={1}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled || isUploading}
        />
        <button
          onClick={submit}
          disabled={disabled || isUploading || !value.trim()}
          className="
            rounded-xl bg-zinc-800 text-white px-4 py-2 text-sm font-medium 
            disabled:opacity-40 hover:bg-zinc-700 transition-colors h-10
            flex items-center justify-center active:scale-95
          "
        >
          Send
        </button>
      </div>
    </div>
  )
}

