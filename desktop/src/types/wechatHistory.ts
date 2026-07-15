export interface WeChatHistoryMessage {
  timestamp: number | null;
  time: string;
  sender: string;
  content: string;
  type: string;
  local_id: number | string | null;
  url?: string | null;
  sender_username?: string | null;
  sender_contact_display?: string | null;
  sender_group_nickname?: string | null;
}

export interface WeChatHistoryMeta {
  status: string;
  unknown_shards_count: number;
  chat_latest_timestamp?: number | null;
  session_last_timestamp?: number | null;
}

export interface WeChatHistoryResult {
  result_id: string;
  task_id?: string | null;
  conversation_id?: string | null;
  chat: string;
  is_group: boolean;
  chat_type: string;
  count: number;
  messages: WeChatHistoryMessage[];
  meta: WeChatHistoryMeta;
  warnings: string[];
  sensitive: true;
  persist: false;
}
