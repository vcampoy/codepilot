import { useEffect, useId, useRef } from 'react'
import type { FormEvent, KeyboardEvent, ReactNode } from 'react'

const FOCUSABLE_SELECTOR = 'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'

type TableFilterDialogProps = {
  children: ReactNode
  open: boolean
  title: string
  onApply: () => void
  onCancel: () => void
}

export function TableFilterDialog({ children, open, title, onApply, onCancel }: TableFilterDialogProps) {
  const dialogRef = useRef<HTMLFormElement>(null)
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

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onApply()
  }
  const keepFocusInside = (event: KeyboardEvent<HTMLFormElement>) => {
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

  return (
    <div className="filter-dialog-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) onCancel() }}>
      <form
        aria-labelledby={titleId}
        aria-modal="true"
        className="filter-dialog"
        onKeyDown={keepFocusInside}
        onSubmit={submit}
        ref={dialogRef}
        role="dialog"
      >
        <h2 id={titleId}>{title}</h2>
        <div className="filter-dialog-content">{children}</div>
        <div className="filter-dialog-actions">
          <button className="secondary-button" onClick={onCancel} type="button">Cancel</button>
          <button type="submit">Apply</button>
        </div>
      </form>
    </div>
  )
}
