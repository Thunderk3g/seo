// ChatPage — primary surface for the Bajaj SEO assistant.
//
// The conversation is held client-side (useChatStream → localStorage)
// and the backend at /api/v1/seo/chat/stream/ owns tool dispatch via
// the LLM. This page does layout + scroll behaviour only.

import { useEffect, useRef } from 'react';
import { useActiveSite } from '../api/hooks/useActiveSite';
import { useChatStream } from '../api/hooks/useChatStream';
import { useWebsites } from '../api/hooks/useWebsites';
import ChatBubble from '../components/chat/ChatBubble';
import Composer from '../components/chat/Composer';

const DEFAULT_DOMAIN = 'bajajlifeinsurance.com';

const SUGGESTIONS = [
  'How are we doing in search this week?',
  'Show our top 10 keyword opportunities',
  'Which competitors are ranking ahead of us, and where?',
  'What pages are missing meta descriptions?',
  'Start a fresh SEO grading run',
];

export default function ChatPage() {
  const { activeSiteId } = useActiveSite();
  const websites = useWebsites();
  const sites = websites.data?.results ?? [];
  const active = sites.find((s) => s.id === activeSiteId);
  const domain = (active?.domain || DEFAULT_DOMAIN).replace(/^https?:\/\//, '');

  const { messages, streaming, send, stop, clear } = useChatStream(domain);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Stick to bottom whenever messages or streaming state change.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, streaming]);

  const lastIdx = messages.length - 1;
  const empty = messages.length === 0;

  return (
    <div className="chat-page">
      <header className="chat-page-head">
        <div>
          <h1 className="chat-page-title">Bajaj SEO Assistant</h1>
          <div className="chat-page-sub">
            How can I help with <strong>{domain}</strong>?
          </div>
        </div>
        {messages.length > 0 && (
          <button
            type="button"
            className="chat-page-clear"
            onClick={clear}
            disabled={streaming}
          >
            New conversation
          </button>
        )}
      </header>

      <div className="chat-scroll" ref={scrollRef}>
        {empty ? (
          <div className="chat-empty">
            <p>Ask anything about Bajaj search performance, content, competitors, or technical health.</p>
            <div className="chat-suggestions">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="chat-suggestion"
                  onClick={() => send(s)}
                  disabled={streaming}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((m, i) => (
            <ChatBubble
              key={i}
              message={m}
              streaming={streaming && i === lastIdx}
            />
          ))
        )}
      </div>

      <div className="chat-footer">
        <Composer
          disabled={streaming}
          streaming={streaming}
          onSend={send}
          onStop={stop}
        />
      </div>
    </div>
  );
}
