import { useEffect, useId, useRef } from 'react'
import type { FormEvent, KeyboardEvent, ReactNode } from 'react'

const FOCUSABLE_SELECTOR = 'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'

type ModalDialogProps = {
  children: ReactNode
  footer: ReactNode
  open: boolean
  title: string
  onCancel: () => void
  onSubmit?: () => void
  className?: string
}

export function ModalDialog({ children, footer, open, title, onCancel, onSubmit, className = 'filter-dialog' }: ModalDialogProps) {
  const dialogRef = useRef<HTMLElement>(null)
  const returnFocusRef = useRef<HTMLElement | null>(null)
  const onCancelRef = useRef(onCancel)
  const titleId = useId()
  onCancelRef.current = onCancel

  useEffect(() => {
    if (!open) return

    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const focusFrame = window.requestAnimationFrame(() => {
      dialogRef.current?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR)?.focus()
    })
    const cancelOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      onCancelRef.current()
    }
    document.addEventListener('keydown', cancelOnEscape)

    return () => {
      window.cancelAnimationFrame(focusFrame)
      document.removeEventListener('keydown', cancelOnEscape)
      returnFocusRef.current?.focus()
    }
  }, [open])

  if (!open) return null

  const keepFocusInside = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== 'Tab') return
    const focusable = [...(dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR) ?? [])]
    if (focusable.length === 0) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  const content = (
    <>
      <h2 id={titleId}>{title}</h2>
      <div className="filter-dialog-content">{children}</div>
      <div className="filter-dialog-actions">{footer}</div>
    </>
  )

  return (
    <div className="filter-dialog-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) onCancel() }}>
      {onSubmit ? (
        <form
          aria-labelledby={titleId}
          aria-modal="true"
          className={className}
          onKeyDown={keepFocusInside}
          onSubmit={(event: FormEvent<HTMLFormElement>) => { event.preventDefault(); onSubmit() }}
          ref={(node) => { dialogRef.current = node }}
          role="dialog"
        >
          {content}
        </form>
      ) : (
        <div aria-labelledby={titleId} aria-modal="true" className={className} onKeyDown={keepFocusInside} ref={(node) => { dialogRef.current = node }} role="dialog">
          {content}
        </div>
      )}
    </div>
  )
}
