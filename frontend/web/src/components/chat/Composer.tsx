// Auto-growing textarea + send button. Enter sends, Shift+Enter newline.
// Grows unbounded — no internal scroll on long messages per design.

import { useEffect, useRef, useState, type KeyboardEvent } from 'react';

interface Props {
  disabled?: boolean;
  streaming?: boolean;
  onSend: (text: string) => void;
  onStop?: () => void;
  placeholder?: string;
  /** Larger min-height + bigger type for the "empty / hero" centred layout. */
  hero?: boolean;
}

export default function Composer({
  disabled,
  streaming,
  onSend,
  onStop,
  placeholder,
  hero,
}: Props) {
  const [value, setValue] = useState('');
  const ref = useRef<HTMLTextAreaElement | null>(null);

  // Auto-resize. Reset height to auto so scrollHeight reflects content.
  // No max — long messages grow the textarea instead of scrolling internally.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = el.scrollHeight + 'px';
  }, [value]);

  function submit() {
    const text = value.trim();
    if (!text || disabled) return;
    onSend(text);
    setValue('');
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter = newline (default textarea behaviour, do nothing).
    // Ctrl+Enter / Cmd+Enter = send (power-user shortcut). The
    // arrow button on the right is the primary send affordance.
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      submit();
    }
  }

  const canSend = !disabled && value.trim().length > 0;

  return (
    <div className={`chat-composer ${hero ? 'chat-composer--hero' : ''}`}>
      <textarea
        ref={ref}
        className="chat-composer-input"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={onKeyDown}
        rows={hero ? 3 : 1}
        placeholder={
          placeholder ||
          'Ask about Bajaj search performance, competitors, content gaps… (Enter = new line, click the arrow to send)'
        }
        disabled={disabled}
      />
      {streaming && onStop ? (
        <button
          type="button"
          className="chat-composer-stop"
          onClick={onStop}
          title="Stop streaming"
          aria-label="Stop streaming"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden>
            <rect x="3" y="3" width="8" height="8" rx="1.5" fill="currentColor" />
          </svg>
        </button>
      ) : (
        <button
          type="button"
          className="chat-composer-send"
          onClick={submit}
          disabled={!canSend}
          title={canSend ? 'Send (Ctrl/Cmd+Enter)' : 'Type a message first'}
          aria-label="Send message"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden>
            <path
              d="M12 4 L12 20 M5 11 L12 4 L19 11"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              fill="none"
            />
          </svg>
        </button>
      )}
    </div>
  );
}
