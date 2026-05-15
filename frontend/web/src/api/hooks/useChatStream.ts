// useChatStream — talks to /api/v1/seo/chat/stream/ over SSE.
//
// The backend is stateless per turn; this hook owns the transcript,
// persists it to localStorage, and reposts the whole thing each send.
// Parses the SSE byte stream with fetch + ReadableStream (no extra
// dep) so it works in the same fetch wrapper the rest of the app uses.

import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  ChatCard,
  ChatMessage,
  ChatToolCall,
} from '../seoTypes';

const STORAGE_PREFIX = 'bajaj.chat.';
const MAX_TURNS = 50;
const CHAT_URL = '/api/v1/seo/chat/stream/';

function storageKey(domain: string): string {
  return `${STORAGE_PREFIX}${domain}`;
}

function loadFromLS(domain: string): ChatMessage[] {
  try {
    const raw = localStorage.getItem(storageKey(domain));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as ChatMessage[]) : [];
  } catch {
    return [];
  }
}

function saveToLS(domain: string, messages: ChatMessage[]): void {
  try {
    // Cap stored turns. One "turn" is roughly one user + one assistant.
    const trimmed = messages.slice(-MAX_TURNS * 2);
    localStorage.setItem(storageKey(domain), JSON.stringify(trimmed));
  } catch {
    // Quota or private-browsing — silently degrade to in-memory only.
  }
}

interface SseFrame {
  event: string;
  data: unknown;
}

// Parse the raw text buffer for any complete `event: ...\ndata: ...\n\n`
// frames. Returns parsed frames and the leftover (incomplete) buffer.
function drainFrames(buffer: string): { frames: SseFrame[]; rest: string } {
  const frames: SseFrame[] = [];
  let rest = buffer;
  while (true) {
    const sep = rest.indexOf('\n\n');
    if (sep === -1) break;
    const block = rest.slice(0, sep);
    rest = rest.slice(sep + 2);
    let event = 'message';
    const dataLines: string[] = [];
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
    }
    if (dataLines.length === 0) continue;
    const dataStr = dataLines.join('\n');
    try {
      frames.push({ event, data: JSON.parse(dataStr) });
    } catch {
      frames.push({ event, data: dataStr });
    }
  }
  return { frames, rest };
}

export interface UseChatStream {
  messages: ChatMessage[];
  streaming: boolean;
  error: string | null;
  send: (text: string) => Promise<void>;
  stop: () => void;
  clear: () => void;
}

export function useChatStream(domain: string): UseChatStream {
  const [messages, setMessages] = useState<ChatMessage[]>(() =>
    loadFromLS(domain)
  );
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Refresh from LS when the domain changes (e.g. project picker).
  useEffect(() => {
    setMessages(loadFromLS(domain));
  }, [domain]);

  useEffect(() => {
    saveToLS(domain, messages);
  }, [domain, messages]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setStreaming(false);
  }, []);

  const clear = useCallback(() => {
    setMessages([]);
    try {
      localStorage.removeItem(storageKey(domain));
    } catch {
      // ignore
    }
  }, [domain]);

  const send = useCallback(
    async (text: string) => {
      const userMsg: ChatMessage = {
        role: 'user',
        content: text,
        timestamp: Date.now(),
      };
      // Snapshot the post-user history so we send the full transcript
      // (the backend is stateless).
      const history = [...messages, userMsg];
      setMessages(history);
      setStreaming(true);
      setError(null);

      const controller = new AbortController();
      abortRef.current = controller;

      // The assistant message we'll mutate as tokens arrive.
      const assistantIdx = history.length;
      const assistantMsg: ChatMessage = {
        role: 'assistant',
        content: '',
        toolCalls: [],
        cards: [],
        timestamp: Date.now(),
      };
      setMessages([...history, assistantMsg]);

      // Local mirror — useState updates are batched, so we keep our
      // own buffer and re-write the assistant slot from it.
      const local = { ...assistantMsg };
      const flush = () => {
        setMessages((prev) => {
          const copy = prev.slice();
          copy[assistantIdx] = { ...local };
          return copy;
        });
      };

      try {
        const resp = await fetch(CHAT_URL, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Accept: 'text/event-stream',
          },
          body: JSON.stringify({
            domain,
            messages: history.map((m) => ({
              role: m.role,
              content: m.content,
            })),
          }),
          signal: controller.signal,
        });
        if (!resp.ok || !resp.body) {
          throw new Error(`chat stream failed: ${resp.status}`);
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buf = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const { frames, rest } = drainFrames(buf);
          buf = rest;
          for (const f of frames) {
            handleFrame(f, local);
          }
          if (frames.length) flush();
        }
        // Final drain in case the stream ended mid-buffer.
        buf += decoder.decode();
        const { frames } = drainFrames(buf + '\n\n');
        for (const f of frames) handleFrame(f, local);
        flush();
      } catch (err) {
        if ((err as DOMException).name !== 'AbortError') {
          const msg = (err as Error).message || 'unknown error';
          setError(msg);
          local.content += `\n\n_⚠️ ${msg}_`;
          flush();
        }
      } finally {
        setStreaming(false);
        abortRef.current = null;
      }
    },
    [domain, messages]
  );

  return { messages, streaming, error, send, stop, clear };
}

function handleFrame(frame: SseFrame, local: ChatMessage): void {
  const data = (frame.data ?? {}) as Record<string, unknown>;
  switch (frame.event) {
    case 'token':
      local.content += String(data.text ?? '');
      break;
    case 'tool_call': {
      const call: ChatToolCall = {
        id: String(data.id ?? ''),
        name: String(data.name ?? ''),
        args: (data.args as Record<string, unknown>) || {},
        result: data.result,
      };
      local.toolCalls = [...(local.toolCalls || []), call];
      break;
    }
    case 'card': {
      const card: ChatCard = {
        card_type: String(data.card_type ?? ''),
        payload: (data.payload as Record<string, unknown>) || {},
      };
      local.cards = [...(local.cards || []), card];
      break;
    }
    case 'done':
      local.tokensIn = Number(data.tokens_in ?? 0);
      local.tokensOut = Number(data.tokens_out ?? 0);
      local.costUsd = Number(data.cost_usd ?? 0);
      break;
    case 'error':
      local.content += `\n\n_⚠️ ${String(data.message ?? 'stream error')}_`;
      break;
    default:
      // Ignore unknown events.
      break;
  }
}
