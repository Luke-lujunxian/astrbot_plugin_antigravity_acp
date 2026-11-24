/**
 * #28-safe copy helper for HTTP and sandboxed iframes.
 *
 * Initiates navigator.clipboard.writeText and executes synchronous
 * document.execCommand('copy') within the SAME click user gesture, so
 * awaiting a rejecting Clipboard Promise never misses the gesture window.
 */
export interface CopyOptions {
  sourceInput?: HTMLInputElement | HTMLTextAreaElement | null;
  returnFocusEl?: HTMLElement | null;
  isDisposed?: () => boolean;
}

export type CopyOutcome = 'empty' | 'copied' | 'manual' | 'stale';

let copyAttemptCounter = 0;

export async function copyTextSafely(text: string, options: CopyOptions = {}): Promise<CopyOutcome> {
  if (!text) return 'empty';
  const attempt = ++copyAttemptCounter;
  const { sourceInput, returnFocusEl, isDisposed } = options;

  let clipboardWrite: Promise<boolean> | undefined;
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      clipboardWrite = Promise.resolve(navigator.clipboard.writeText(text)).then(
        () => true,
        () => false,
      );
    }
  } catch {
    // Accessing or invoking Clipboard API can throw synchronously in restricted contexts.
  }

  let copied = false;
  const buffer = document.createElement('textarea');
  try {
    buffer.value = text;
    buffer.readOnly = true;
    buffer.className = 'copy-buffer';
    buffer.setAttribute('aria-hidden', 'true');
    buffer.tabIndex = -1;
    document.body.appendChild(buffer);
    buffer.focus({ preventScroll: true });
    buffer.select();
    copied = typeof document.execCommand === 'function' ? document.execCommand('copy') : false;
  } catch {
    copied = false;
  } finally {
    buffer.remove();
    try {
      returnFocusEl?.focus({ preventScroll: true });
    } catch {
      // Ignore focus errors if element detached.
    }
  }

  if (!copied && clipboardWrite) {
    copied = await clipboardWrite;
  }

  if (isDisposed?.() || attempt !== copyAttemptCounter) {
    return 'stale';
  }
  if (sourceInput && sourceInput.value !== text) {
    return 'stale';
  }

  if (!copied && sourceInput) {
    try {
      sourceInput.focus();
      sourceInput.select();
    } catch {
      // Ignore selection failure on detached inputs.
    }
  }

  return copied ? 'copied' : 'manual';
}

export function openExternalUrlSafely(url: string): boolean {
  if (!url) return false;
  try {
    return Boolean(window.open(url, '_blank', 'noopener'));
  } catch {
    return false;
  }
}
