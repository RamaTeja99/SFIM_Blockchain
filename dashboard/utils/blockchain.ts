export interface BlockchainEvent {
  type: string;
  data: any;
  timestamp: number;
}

export class BlockchainClient {
  private ws: WebSocket | null = null;
  private reconnectTimeout: NodeJS.Timeout | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000; // Start with 1 second

  constructor(private url: string) {}

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        this.ws = new WebSocket(this.url);

        this.ws.onopen = () => {
          console.log('Blockchain WebSocket connected');
          this.reconnectAttempts = 0;
          this.reconnectDelay = 1000;
          resolve();
        };

        this.ws.onerror = (error) => {
          console.error('Blockchain WebSocket error:', error);
          reject(error);
        };

        this.ws.onclose = () => {
          console.log('Blockchain WebSocket closed');
          this.scheduleReconnect();
        };

      } catch (error) {
        reject(error);
      }
    });
  }

  private scheduleReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('Max reconnection attempts reached');
      return;
    }

    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
    }

    this.reconnectTimeout = setTimeout(() => {
      console.log(`Attempting to reconnect (attempt ${this.reconnectAttempts + 1})`);
      this.reconnectAttempts++;
      this.reconnectDelay *= 2; // Exponential backoff

      this.connect().catch(() => {
        // Reconnect failed, will try again
      });
    }, this.reconnectDelay);
  }

  send(message: any): boolean {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
      return true;
    }
    return false;
  }

  onMessage(callback: (event: BlockchainEvent) => void) {
    if (this.ws) {
      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          callback({
            type: data.type || 'unknown',
            data: data,
            timestamp: Date.now(),
          });
        } catch (error) {
          console.error('Error parsing blockchain message:', error);
        }
      };
    }
  }

  disconnect() {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}

// Utility functions for data formatting
export function formatHash(hash: string, length = 16): string {
  if (!hash) return '';
  return hash.length > length ? `${hash.substring(0, length)}...` : hash;
}

export function formatTimestamp(timestamp: string | number): string {
  const date = new Date(timestamp);
  return date.toLocaleString();
}

export function calculateTrustScore(quotes: any[]): number {
  if (!quotes.length) return 0;

  const trustedCount = quotes.filter(q => q.trust_level === 'trusted').length;
  return Math.round((trustedCount / quotes.length) * 100);
}

export function getStatusColor(status: string): string {
  switch (status.toLowerCase()) {
    case 'committed':
    case 'trusted':
    case 'active':
      return 'green';
    case 'pending':
    case 'suspicious':
      return 'yellow';
    case 'rejected':
    case 'untrusted':
    case 'inactive':
      return 'red';
    default:
      return 'blue';
  }
}

// API client for REST endpoints
export class ApiClient {
  constructor(private baseUrl: string) {}

  async get(endpoint: string): Promise<any> {
    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error(`API request failed: ${response.statusText}`);
    }

    return response.json();
  }

  async post(endpoint: string, data: any): Promise<any> {
    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
    });

    if (!response.ok) {
      throw new Error(`API request failed: ${response.statusText}`);
    }

    return response.json();
  }

  async uploadFile(endpoint: string, file: File): Promise<any> {
    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`File upload failed: ${response.statusText}`);
    }

    return response.json();
  }
}
