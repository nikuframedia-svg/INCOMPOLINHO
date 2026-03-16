/**
 * ChatMessage — renders a single message in the copilot chat.
 */

import type { DisplayMessage } from './useCopilot';

interface ChatMessageProps {
  message: DisplayMessage;
}

export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === 'user';

  return (
    <div className={`chat-message ${isUser ? 'chat-message--user' : 'chat-message--assistant'}`}>
      <div className="chat-message__bubble">
        <div className="chat-message__content">{message.content}</div>
        {message.toolCalls != null && message.toolCalls > 0 && (
          <div className="chat-message__tools">
            {message.toolCalls}{' '}
            {message.toolCalls === 1 ? 'ferramenta executada' : 'ferramentas executadas'}
          </div>
        )}
      </div>
    </div>
  );
}
