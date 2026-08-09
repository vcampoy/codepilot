import type { ReactNode } from 'react'
import { ModalDialog } from './ModalDialog'

type TableFilterDialogProps = {
  children: ReactNode
  open: boolean
  title: string
  onApply: () => void
  onCancel: () => void
}

export function TableFilterDialog({ children, open, title, onApply, onCancel }: TableFilterDialogProps) {
  return (
    <ModalDialog
      footer={<>
        <button className="secondary-button" onClick={onCancel} type="button">Cancel</button>
        <button type="submit">Apply</button>
      </>}
      open={open}
      onCancel={onCancel}
      onSubmit={onApply}
      title={title}
    >
      {children}
    </ModalDialog>
  )
}
