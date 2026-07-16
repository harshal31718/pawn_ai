import { useRef, useState, useEffect, type KeyboardEvent } from 'react'
import KebabMenu from './KebabMenu'
import ModelSwitcher from './ModelSwitcher'
import { PlusIcon } from './icons'
import type { RegistryModel } from '../api/client'

interface Props {
  value: string
  onChange: (value: string) => void
  onSend: (content: string) => void
  onStop?: () => void
  disabled?: boolean
  onUpload?: (file: File) => void
  isUploading?: boolean
  /** F-11: attach an image for a one-turn vision Q&A (not RAG-indexed, not
   *  image generation) -- separate from the PDF attach flow above. */
  onUploadImage?: (file: File) => void
  selectedProvider?: string
  onChangeProvider?: (id: string) => void
  models?: RegistryModel[]
  /** Attached document chip, rendered INSIDE the input island (2026-07-13 UX
   *  fix: the chip used to float loose above the input over the canvas). */
  attachment?: { name: string } | null
  onRemoveAttachment?: () => void
  /** F-11: attached image chip -- shows a thumbnail instead of a filename
   *  row. Mutually exclusive with `attachment` in practice (one attachment
   *  per turn), kept as a separate prop pair to mirror the doc attachment's
   *  own shape rather than overloading one prop with a union. */
  imageAttachment?: { name: string; previewUrl: string } | null
  onRemoveImageAttachment?: () => void
}

export default function MessageInput({
  value,
  onChange,
  onSend,
  onStop,
  disabled = false,
  onUpload,
  isUploading = false,
  onUploadImage,
  selectedProvider = '',
  onChangeProvider,
  models = [],
  attachment = null,
  onRemoveAttachment,
  imageAttachment = null,
  onRemoveImageAttachment,
}: Props) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const imageInputRef = useRef<HTMLInputElement>(null)
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
  const hasAnyAttachment = Boolean(attachment || imageAttachment)

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

  function handleImageFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    onUploadImage?.(file)
    if (imageInputRef.current) {
      imageInputRef.current.value = ''
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
      <input
        type="file"
        ref={imageInputRef}
        onChange={handleImageFileChange}
        accept="image/*"
        className="hidden"
        id="image-upload-input"
      />

      {/* Unified Connected Island Input */}
      <div className={`
        w-full bg-theme-surface transition-all duration-300
        flex flex-wrap gap-2
        ${disabled ? 'border border-theme-border/40 opacity-75' : 'border border-theme-border'}
        ${isMultiLine || hasAnyAttachment
          ? 'items-end p-3 rounded-3xl shadow-lg'
          : 'items-center px-3 py-1.5 rounded-full shadow-md'}
      `}>
        {/* 0. Attached document/image chip — lives inside the island, above the textarea */}
        {(attachment || imageAttachment) && (
          <div className="w-full order-0 flex">
            <div className="inline-flex items-center gap-1.5 bg-theme-bg border border-theme-border/60 rounded-lg px-2 py-1 text-xs text-theme-text select-none animate-in fade-in zoom-in duration-200">
              {imageAttachment ? (
                <img
                  src={imageAttachment.previewUrl}
                  alt={imageAttachment.name}
                  className="w-4.5 h-4.5 rounded object-cover shrink-0"
                />
              ) : (
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-3.5 h-3.5 text-theme-text-muted shrink-0">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                </svg>
              )}
              <span className="font-medium truncate max-w-[200px]">
                {imageAttachment ? imageAttachment.name : attachment!.name}
              </span>
              {(imageAttachment ? onRemoveImageAttachment : onRemoveAttachment) && (
                <button
                  type="button"
                  onClick={imageAttachment ? onRemoveImageAttachment : onRemoveAttachment}
                  disabled={disabled}
                  className="ml-1 text-theme-text-muted hover:text-theme-text disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none"
                  title="Remove attachment"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-3.5 h-3.5">
                    <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
                  </svg>
                </button>
              )}
            </div>
          </div>
        )}

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

        {/* 3. Attach Button — "+" opens a kebab-style menu (F-11): Attach PDF
            (unchanged) and Attach image (new, vision Q&A). */}
        <div className={`shrink-0 ${isMultiLine ? 'order-3' : 'order-1'}`}>
          <KebabMenu
            title="Attach"
            icon={<PlusIcon className="w-5 h-5" />}
            buttonClassName="rounded-full p-2 text-theme-text-muted hover:text-theme-text hover:bg-theme-bg/50 disabled:opacity-40 disabled:cursor-not-allowed transition-all shrink-0 flex items-center justify-center h-9 w-9 active:scale-95 cursor-pointer"
            items={[
              { label: 'Attach PDF', onClick: () => fileInputRef.current?.click() },
              { label: 'Attach image', onClick: () => imageInputRef.current?.click() },
            ]}
          />
        </div>

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
