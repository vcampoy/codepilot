import type { ReactNode } from 'react'
import { ModalDialog } from './ModalDialog'

type ConfirmationDialogProps = {
  children: ReactNode
  confirmLabel: string
  open: boolean
  title: string
  busy?: boolean
  onCancel: () => void
  onConfirm: () => void
}

export function ConfirmationDialog({
  children,
  confirmLabel,
  open,
  title,
  busy = false,
  onCancel,
  onConfirm,
}: ConfirmationDialogProps) {
  return (
    <ModalDialog
      className="confirmation-dialog"
      footer={<>
        <button className="secondary-button" disabled={busy} onClick={onCancel} type="button">Cancel</button>
        <button
          className="danger-button confirmation-dialog-confirm"
          disabled={busy}
          onClick={onConfirm}
          type="button"
        >
          {busy ? 'Deleting...' : confirmLabel}
        </button>
      </>}
      open={open}
      onCancel={onCancel}
      title={title}
    >
      <p>{children}</p>
    </ModalDialog>
  )
}
