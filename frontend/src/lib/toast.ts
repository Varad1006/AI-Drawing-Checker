export type ToastKind = 'info' | 'success' | 'error';
export interface ToastEvent {
  id: number;
  message: string;
  kind: ToastKind;
}

let next = 1;
export function toast(message: string, kind: ToastKind = 'info') {
  window.dispatchEvent(new CustomEvent<ToastEvent>('lc-toast', { detail: { id: next++, message, kind } }));
}
