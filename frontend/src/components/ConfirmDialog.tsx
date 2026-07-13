interface Props {
  open: boolean
  title: string
  message: React.ReactNode
  confirmLabel?: string
  cancelLabel?: string
  destructive?: boolean
  onConfirm: () => void
  onCancel: () => void
}

/** Blocking, centered confirm dialog — used for the three project flows
 *  (add-to-project, remove-from-project, delete-project) that the plan
 *  requires as explicit confirms rather than the sidebar's inline
 *  delete-chat popup. */
export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  destructive = false,
  onConfirm,
  onCancel,
}: Props) {
  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 animate-in fade-in duration-150"
      onClick={onCancel}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-sm mx-4 bg-theme-surface border border-theme-border rounded-2xl shadow-2xl p-5 animate-in zoom-in-95 duration-150"
      >
        <h2 className="text-sm font-semibold text-theme-text mb-2">{title}</h2>
        <div className="text-xs text-theme-text-muted leading-relaxed mb-5">{message}</div>
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-3 h-8 rounded-lg border border-theme-border hover:bg-theme-surface-hover text-theme-text text-xs font-semibold transition-colors active:scale-95 cursor-pointer"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className={`px-3 h-8 rounded-lg text-xs font-semibold transition-colors active:scale-95 cursor-pointer border ${
              destructive
                ? 'bg-red-600 hover:bg-red-700 text-white border-red-700'
                : 'bg-theme-brand hover:opacity-90 text-theme-brand-text border-transparent'
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
