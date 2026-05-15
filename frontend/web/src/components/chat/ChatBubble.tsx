// One conversation turn — user, assistant, or tool message.
// Assistant messages may also carry tool-call chips and inline cards.

import type { ChatMessage } from '../../api/seoTypes';
import CardRenderer from './cards';
import { Markdown } from './Markdown';
import ToolCallChip from './ToolCallChip';

export default function ChatBubble({
  message,
  streaming,
}: {
  message: ChatMessage;
  streaming?: boolean;
}) {
  const isUser = message.role === 'user';
  const isAssistant = message.role === 'assistant';
  return (
    <div className={`chat-row ${message.role}`}>
      <div className={`chat-bubble ${message.role}`}>
        {isUser ? (
          <div className="chat-user-text">{message.content}</div>
        ) : (
          <>
            {(message.toolCalls?.length ?? 0) > 0 && (
              <div className="chat-tool-chips">
                {message.toolCalls!.map((tc, i) => (
                  <ToolCallChip key={i} call={tc} />
                ))}
              </div>
            )}
            {message.content ? (
              <Markdown source={message.content} />
            ) : streaming && isAssistant ? (
              <span className="chat-typing">
                <span />
                <span />
                <span />
              </span>
            ) : null}
            {(message.cards?.length ?? 0) > 0 && (
              <div className="chat-cards">
                {message.cards!.map((c, i) => (
                  <CardRenderer key={i} card={c} />
                ))}
              </div>
            )}
            {isAssistant && message.tokensOut != null && (
              <div className="chat-bubble-meta">
                {message.tokensIn}↑ / {message.tokensOut}↓ tok
                {message.costUsd != null
                  ? ` · $${message.costUsd.toFixed(4)}`
                  : ''}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
