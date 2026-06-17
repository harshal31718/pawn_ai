import { useEffect, useRef, useState } from 'react'
import type { Message } from './types'
import ChatWindow from './components/ChatWindow'
import MessageInput from './components/MessageInput'
import ModelSwitcher from './components/ModelSwitcher'
import { healthCheck, streamChat, uploadDoc } from './api/client'

let nextId = 1

export default function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [selectedProvider, setSelectedProvider] = useState('gemini')
  
  // Document upload states
  const [attachedDoc, setAttachedDoc] = useState<{ id: string; name: string } | null>(null)
  const [isUploading, setIsUploading] = useState(false)

  const streamingIdRef = useRef<string | null>(null)

  useEffect(() => {
    healthCheck()
      .then((data) => console.log('Backend:', data))
      .catch((err) => console.error('Backend unreachable:', err))
  }, [])

  async function handleSend(content: string) {
    if (isStreaming || isUploading) return

    const userMsg: Message = { id: String(nextId++), role: 'user', content }
    const assistantId = String(nextId++)
    streamingIdRef.current = assistantId

    setMessages((prev) => [
      ...prev,
      userMsg,
      { id: assistantId, role: 'assistant', content: '' },
    ])
    setIsStreaming(true)

    const history = [...messages, userMsg].map((m) => ({
      role: m.role,
      content: m.content,
    }))

    await streamChat(
      history,
      {
        onToken: (delta) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: m.content + delta } : m,
            ),
          )
        },
        onDone: () => {
          setIsStreaming(false)
          streamingIdRef.current = null
        },
        onError: (err) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, content: `Error: ${err}` }
                : m,
            ),
          )
          setIsStreaming(false)
          streamingIdRef.current = null
        },
        // Future callbacks wired here as steps land:
        // onStep, onMemoryHit, onModelCall, onProviderSwitch
      },
      selectedProvider,
      attachedDoc?.id || undefined,
    )
  }

  async function handleUpload(file: File) {
    setIsUploading(true)
    try {
      const docId = await uploadDoc(file)
      setAttachedDoc({ id: docId, name: file.name })
    } catch (err: any) {
      alert(`Upload failed: ${err.message}`)
    } finally {
      setIsUploading(false)
    }
  }

  return (
    <div className="flex flex-col h-screen bg-white">
      <header className="border-b border-zinc-200 px-4 py-2 shrink-0 flex items-center justify-between">
        <h1 className="text-sm font-semibold text-zinc-800">PAWN</h1>
        <ModelSwitcher
          selected={selectedProvider}
          onChange={setSelectedProvider}
          disabled={isStreaming || isUploading}
        />
      </header>
      
      <ChatWindow messages={messages} />
      
      {attachedDoc && (
        <div className="px-4 py-2 bg-zinc-50 border-t border-zinc-200 flex items-center shrink-0">
          <div className="flex items-center gap-1.5 bg-zinc-100 border border-zinc-300 rounded-lg px-2.5 py-1 text-xs text-zinc-700 select-none animate-in fade-in zoom-in duration-200">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-3.5 h-3.5 text-zinc-500 shrink-0">
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
            </svg>
            <span className="font-medium truncate max-w-[200px]">{attachedDoc.name}</span>
            <button
              type="button"
              onClick={() => setAttachedDoc(null)}
              disabled={isStreaming}
              className="ml-1 text-zinc-400 hover:text-zinc-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none"
              title="Remove attachment"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-3.5 h-3.5">
                <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
              </svg>
            </button>
          </div>
        </div>
      )}

      <MessageInput
        onSend={handleSend}
        disabled={isStreaming}
        onUpload={handleUpload}
        isUploading={isUploading}
      />
    </div>
  )
}
