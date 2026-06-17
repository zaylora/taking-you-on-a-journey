export interface NodeStartPayload {
  node: string;
}

export interface TokenPayload {
  text: string;
}

export interface NodeEndPayload {
  node: string;
}

export interface FinalPayload {
  answer: string;
}

export interface ErrorPayload {
  message: string;
}

export type EventName = 'node_start' | 'token' | 'node_end' | 'final' | 'error';
