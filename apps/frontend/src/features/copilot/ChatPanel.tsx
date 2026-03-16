/**
 * ChatPanel — Copilot sidebar chat panel.
 *
 * Fixed right sidebar, 380px, collapsible.
 * Shows conversation history + input.
 */

import { MessageSquare, Minus, Send, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ChatMessage } from './ChatMessage';
import {
  useCopilotActions,
  useCopilotError,
  useCopilotLoading,
  useCopilotMessages,
} from './useCopilot';
import './ChatPanel.css';

interface ChatPanelProps {
  open: boolean;
  onClose: () => void;
}

export function ChatPanel({ open, onClose }: ChatPanelProps) {
  const messages = useCopilotMessages();
  const isLoading = useCopilotLoading();
  const error = useCopilotError();
  const { sendMessage, clearMessages, clearError } = useCopilotActions();
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, isLoading]);

  // Focus input when panel opens
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text || isLoading) return;
    setInput('');
    sendMessage(text);
  }, [input, isLoading, sendMessage]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  if (!open) return null;

  return (
    <aside className="chat-panel" aria-label="Copilot">
      <div className="chat-panel__header">
        <div className="chat-panel__title">
          <MessageSquare size={16} />
          <span>Copilot PP1</span>
        </div>
        <div className="chat-panel__header-actions">
          <span className="chat-panel__status">{isLoading ? 'A pensar...' : 'Pronto'}</span>
          <button
            type="button"
            className="chat-panel__btn"
            onClick={() => clearMessages()}
            title="Limpar conversa"
          >
            <Trash2 size={14} />
          </button>
          <button type="button" className="chat-panel__btn" onClick={onClose} title="Minimizar">
            <Minus size={14} />
          </button>
        </div>
      </div>

      <div className="chat-panel__messages">
        {messages.length === 0 && (
          <div className="chat-panel__empty">Pergunte ao copilot sobre o plano de produção.</div>
        )}
        {messages.map((m) => (
          <ChatMessage key={m.id} message={m} />
        ))}
        {isLoading && (
          <div className="chat-message chat-message--assistant">
            <div className="chat-message__bubble chat-message__typing">
              <span />
              <span />
              <span />
            </div>
          </div>
        )}
        {error && (
          <div className="chat-panel__error" onClick={clearError}>
            {error}
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="chat-panel__input-area">
        <input
          ref={inputRef}
          className="chat-panel__input"
          type="text"
          placeholder="Pergunte ao copilot..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isLoading}
        />
        <button
          type="button"
          className="chat-panel__send"
          onClick={handleSend}
          disabled={isLoading || !input.trim()}
          title="Enviar"
        >
          <Send size={16} />
        </button>
      </div>
    </aside>
  );
}
