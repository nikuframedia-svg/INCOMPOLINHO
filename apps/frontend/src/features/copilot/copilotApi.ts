/**
 * copilotApi — HTTP client for the copilot backend.
 */

import { config } from '../../config';
import { fetchWithTimeout } from '../../lib/fetchWithTimeout';

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface CopilotWidget {
  type: string;
  data: Record<string, unknown>;
}

export interface ChatResponse {
  response: string;
  tool_calls_made: number;
  widgets?: CopilotWidget[];
}

export async function sendCopilotMessage(messages: ChatMessage[]): Promise<ChatResponse> {
  const res = await fetchWithTimeout(
    `${config.apiBaseURL}/v1/copilot/chat`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages }),
    },
    15_000,
  );
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Copilot HTTP ${res.status}: ${text}`);
  }
  return res.json();
}

export interface CopilotTool {
  name: string;
  description: string;
}

export async function listCopilotTools(): Promise<CopilotTool[]> {
  const res = await fetchWithTimeout(`${config.apiBaseURL}/v1/copilot/tools`, {}, 5_000);
  if (!res.ok) throw new Error(`Copilot tools HTTP ${res.status}`);
  const data = await res.json();
  return data.tools ?? data;
}
