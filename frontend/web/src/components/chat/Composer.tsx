// Auto-growing textarea + send button. Enter sends, Shift+Enter newline.

import { useEffect, useRef, useState, type KeyboardEvent } from 'react';

interface Props {
  disabled?: boolean;
  streaming?: boolean;
  onSend: (text: string) => void;
  onStop?: () => void;
  placeholder?: string;
}

const MAX_ROWS = 6;
const LINE_HEIGHT_PX = 22;

export default function Composer({
  disabled,
  streaming,
  onSend,
  onStop,
  placeholder,
}: Props) {
  const [value, setValue] = useState('');
  const ref = useRef<HTMLTextAreaElement | null>(null);

  // Auto-resize. Reset height to auto so scrollHeight reflects content.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    const max = LINE_HEIGHT_PX * MAX_ROWS + 16; // 8px padding top+bottom
    el.style.height = Math.min(el.scrollHeight, max) + 'px';
  }, [value]);

  function submit() {
    const text = value.trim();
    if (!text || disabled) return;
    onSend(text);
    setValue('');
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <div className="chat-composer">
      <textarea
        ref={ref}
        className="chat-composer-input"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={onKeyDown}
        rows={1}
        placeholder={placeholder || 'Ask about Bajaj search performance, competitors, content gaps…'}
        disabled={disabled}
      />
      {streaming && onStop ? (
        <button
          type="button"
          className="chat-composer-stop"
          onClick={onStop}
        >
          Stop
        </button>
      ) : (
        <button
          type="button"
          className="chat-composer-send"
          onClick={submit}
          disabled={disabled || !value.trim()}
        >
          Send
        </button>
      )}
    </div>
  );
}
