"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import {
  DocumentTextIcon,
  ShieldCheckIcon,
  CpuChipIcon,
  CheckCircleIcon,
  XCircleIcon,
  ClockIcon,
} from "@heroicons/react/24/outline";

// Types
interface IntegrityEvent {
  id: number;
  merkle_root: string;
  file_path?: string;
  file_hash?: string;
  node_id: number;
  consensus_round: number;
  status: "pending" | "committed" | "rejected";
  timestamp: string;
  created_at: string;
}

interface TPMQuote {
  id: number;
  node_id: number;
  nonce: string;
  is_valid: boolean;
  trust_level: "trusted" | "suspicious" | "untrusted" | "unknown";
  timestamp: string;
}

interface NodeStatus {
  node_id: number;
  is_primary: boolean;
  total_nodes: number;
  connected_peers: number;
  database_url: string;
  use_simulated_tpm: boolean;
  timestamp: number;
}

interface FileUploadResult {
  valid: boolean;
  log: IntegrityEvent;
  error?: string;
}

interface WebSocketMessage {
  type: string;
  data?: any;
  events?: IntegrityEvent[];
  quotes?: TPMQuote[];
  timestamp?: number;
}

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:7000";
const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:7000";

export default function BlockchainIntegrityScanner() {
  // State management
  const [events, setEvents] = useState<IntegrityEvent[]>([]);
  const [quotes, setQuotes] = useState<TPMQuote[]>([]);
  const [nodeStatus, setNodeStatus] = useState<NodeStatus | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<FileUploadResult | null>(
    null
  );
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [activeTab, setActiveTab] = useState("FILE");

  // Refs
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // WebSocket connection management
  const connectWebSocket = useCallback(() => {
    try {
      const ws = new WebSocket(`${WS_URL}/ws`);

      ws.onopen = () => {
        console.log("WebSocket connected");
        setIsConnected(true);
        if (reconnectTimeoutRef.current) {
          clearTimeout(reconnectTimeoutRef.current);
          reconnectTimeoutRef.current = null;
        }
      };

      ws.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);

          if (message.type === "feed_update") {
            if (message.events) {
              setEvents(message.events);
            }
            if (message.quotes) {
              setQuotes(message.quotes);
            }
          }
        } catch (error) {
          console.error("Error parsing WebSocket message:", error);
        }
      };

      ws.onclose = () => {
        console.log("WebSocket disconnected");
        setIsConnected(false);
        wsRef.current = null;

        if (!reconnectTimeoutRef.current) {
          reconnectTimeoutRef.current = setTimeout(() => {
            console.log("Attempting to reconnect...");
            connectWebSocket();
          }, 3000);
        }
      };

      ws.onerror = (error) => {
        console.error("WebSocket error:", error);
        setIsConnected(false);
      };

      wsRef.current = ws;
    } catch (error) {
      console.error("Failed to create WebSocket connection:", error);
      setIsConnected(false);
    }
  }, []);

  // Fetch node status
  const fetchNodeStatus = useCallback(async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/status`);
      if (response.ok) {
        const status = await response.json();
        setNodeStatus(status);
      }
    } catch (error) {
      console.error("Failed to fetch node status:", error);
    }
  }, []);

  // Initialize connections
  useEffect(() => {
    connectWebSocket();
    fetchNodeStatus();

    const statusInterval = setInterval(fetchNodeStatus, 10000);

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      clearInterval(statusInterval);
    };
  }, [connectWebSocket, fetchNodeStatus]);

  // File upload handlers
  const handleFileSelect = (file: File) => {
    setSelectedFile(file);
    setUploadResult(null);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);

    const files = e.dataTransfer.files;
    if (files.length > 0) {
      handleFileSelect(files[0]);
    }
  };

  const uploadFile = async () => {
    if (!selectedFile) return;

    setUploading(true);
    setUploadResult(null);

    try {
      const formData = new FormData();
      formData.append("file", selectedFile);

      const response = await fetch("/api/upload", {
        method: "POST",
        body: formData,
      });

      const result: FileUploadResult = await response.json();
      setUploadResult(result);

      if (result.valid) {
        setTimeout(fetchNodeStatus, 1000);
      }
    } catch (error) {
      console.error("Upload failed:", error);
      setUploadResult({
        valid: false,
        error: "Upload failed. Please try again.",
        log: {} as IntegrityEvent,
      });
    } finally {
      setUploading(false);
    }
  };

  const StatusBadge = ({ status }: { status: string }) => {
    const getStatusClass = (status: string) => {
      switch (status) {
        case "committed":
          return "desktop-badge committed";
        case "pending":
          return "desktop-badge pending";
        case "rejected":
          return "desktop-badge rejected";
        case "trusted":
          return "desktop-badge trusted";
        case "suspicious":
          return "desktop-badge suspicious";
        case "untrusted":
          return "desktop-badge untrusted";
        default:
          return "desktop-badge";
      }
    };

    return <span className={getStatusClass(status)}>{status}</span>;
  };

  return (
    <div className="desktop-wrapper">
      {/* Header */}
      <header className="desktop-header">
        <h1 className="desktop-logo">🔒 BlockchainVerify</h1>
        <p className="desktop-subtitle">
          Analyze files for integrity verification using distributed blockchain
          consensus and TPM attestation
        </p>

        {/* Connection Status */}
        <div className="desktop-connection">
          <div className="desktop-connection-status">
            <div
              className={`desktop-connection-dot ${
                isConnected ? "online" : "offline"
              }`}
            ></div>
            <span className="text-gray-700">
              {isConnected ? "Connected to Network" : "Disconnected"}
            </span>
          </div>
          {nodeStatus && (
            <div className="desktop-connection-status">
              <CpuChipIcon className="w-5 h-5 mr-2 text-blue-600" />
              <span className="text-gray-700">
                Node {nodeStatus.node_id}{" "}
                {nodeStatus.is_primary ? "(Primary)" : "(Backup)"} •{" "}
                {nodeStatus.connected_peers}/{nodeStatus.total_nodes - 1} Peers
              </span>
            </div>
          )}
        </div>

        {/* Tab Navigation */}
        <nav className="desktop-tabs">
          <div
            className={`desktop-tab ${activeTab === "FILE" ? "active" : ""}`}
            onClick={() => setActiveTab("FILE")}
          >
            FILE
          </div>
        </nav>
      </header>

      {/* Main Content - Desktop Layout */}
      <div className="desktop-main">
        {/* Upload Section */}
        <div className="desktop-upload-section">
          {activeTab === "FILE" && (
            <>
              {/* File Upload Area */}
              <div
                className={`desktop-upload-area ${dragOver ? "dragover" : ""}`}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  className="desktop-file-input"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) handleFileSelect(file);
                  }}
                />

                <DocumentTextIcon className="desktop-upload-icon" />
                <div className="desktop-upload-text">
                  {selectedFile ? selectedFile.name : "Choose file"}
                </div>
                <div className="desktop-upload-subtext">or drag it here</div>

                {selectedFile && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      uploadFile();
                    }}
                    disabled={uploading}
                    className="desktop-upload-button"
                  >
                    {uploading ? (
                      <span className="flex items-center">
                        <span className="desktop-spinner mr-3"></span>
                        Verifying...
                      </span>
                    ) : (
                      "Verify File"
                    )}
                  </button>
                )}
              </div>

              {/* Upload Result */}
              {uploadResult && (
                <div
                  className={`desktop-result ${
                    uploadResult.valid ? "success" : "error"
                  }`}
                >
                  <div
                    className={`desktop-result-title ${
                      uploadResult.valid ? "success" : "error"
                    }`}
                  >
                    {uploadResult.valid ? (
                      <CheckCircleIcon className="w-6 h-6 mr-3" />
                    ) : (
                      <XCircleIcon className="w-6 h-6 mr-3" />
                    )}
                    {uploadResult.valid
                      ? "File verified successfully!"
                      : "Verification failed"}
                  </div>
                  {uploadResult.error && (
                    <p className="text-red-700 text-base mt-3">
                      {uploadResult.error}
                    </p>
                  )}
                  {uploadResult.valid && uploadResult.log && (
                    <div className="desktop-result-details">
                      <p>
                        <strong>Hash:</strong>{" "}
                        <span className="desktop-table-hash">
                          {uploadResult.log.file_hash?.substring(0, 32)}...
                        </span>
                      </p>
                      <p>
                        <strong>Consensus Round:</strong>{" "}
                        {uploadResult.log.consensus_round}
                      </p>
                      <p>
                        <strong>Status:</strong>{" "}
                        <StatusBadge status={uploadResult.log.status} />
                      </p>
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {/* Sidebar - Status Cards */}
        <div className="desktop-sidebar">
          <div className="desktop-status-grid">
            <div className="desktop-status-card">
              <h3 className="desktop-status-title">
                <CpuChipIcon className="desktop-status-icon" />
                System Status
              </h3>
              {nodeStatus ? (
                <div className="space-y-1">
                  <div className="desktop-status-item">
                    <span className="desktop-status-label">Node ID:</span>
                    <span className="desktop-status-value">
                      {nodeStatus.node_id}
                    </span>
                  </div>
                  <div className="desktop-status-item">
                    <span className="desktop-status-label">Role:</span>
                    <span className="desktop-status-value">
                      {nodeStatus.is_primary ? "Primary" : "Backup"}
                    </span>
                  </div>
                  <div className="desktop-status-item">
                    <span className="desktop-status-label">
                      Connected Peers:
                    </span>
                    <span className="desktop-status-value">
                      {nodeStatus.connected_peers}/{nodeStatus.total_nodes - 1}
                    </span>
                  </div>
                  <div className="desktop-status-item">
                    <span className="desktop-status-label">TPM Mode:</span>
                    <span className="desktop-status-value">
                      {nodeStatus.use_simulated_tpm ? "Simulated" : "Hardware"}
                    </span>
                  </div>
                </div>
              ) : (
                <p className="text-gray-500 text-base">
                  Loading system status...
                </p>
              )}
            </div>

            <div className="desktop-status-card">
              <h3 className="desktop-status-title">
                <ShieldCheckIcon className="desktop-status-icon" />
                Node Trust Levels
              </h3>
              {quotes.length > 0 ? (
                <div className="space-y-4">
                  {quotes.slice(0, 3).map((quote) => (
                    <div
                      key={quote.id}
                      className="flex items-center justify-between"
                    >
                      <span className="desktop-status-label">
                        Node {quote.node_id}
                      </span>
                      <StatusBadge status={quote.trust_level} />
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-gray-500 text-base">
                  No trust data available
                </p>
              )}
            </div>
          </div>
        </div>

        {/* Events Section - Full Width */}
        <div className="desktop-events">
          <h2 className="desktop-events-title">Recent Integrity Events</h2>

          {events.length > 0 ? (
            <div className="desktop-events-table">
              <table className="w-full">
                <thead className="desktop-table-header">
                  <tr>
                    <th>Merkle Root</th>
                    <th>Node</th>
                    <th>Round</th>
                    <th>Status</th>
                    <th>Timestamp</th>
                  </tr>
                </thead>
                <tbody>
                  {events.slice(0, 10).map((event) => (
                    <tr key={event.id} className="desktop-table-row">
                      <td className="desktop-table-cell">
                        <div className="desktop-table-hash">
                          {event.merkle_root.substring(0, 16)}...
                        </div>
                        {event.file_path && (
                          <div className="text-sm text-gray-500 mt-2">
                            {event.file_path}
                          </div>
                        )}
                      </td>
                      <td className="desktop-table-cell">{event.node_id}</td>
                      <td className="desktop-table-cell">
                        {event.consensus_round}
                      </td>
                      <td className="desktop-table-cell">
                        <StatusBadge status={event.status} />
                      </td>
                      <td className="desktop-table-cell">
                        {new Date(event.timestamp).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="desktop-empty">
              <DocumentTextIcon className="desktop-empty-icon" />
              <h3 className="desktop-empty-title">No integrity events yet</h3>
              <p className="desktop-empty-subtitle">
                Upload files to see integrity verification events here
              </p>
            </div>
          )}
        </div>

        {/* Legal Notice */}
        <div className="desktop-legal">
          <p className="desktop-legal-text">
            By uploading a file, you agree to our{" "}
            <a href="#" className="desktop-legal-link">
              Terms of Service
            </a>{" "}
            and{" "}
            <a href="#" className="desktop-legal-link">
              Privacy Policy
            </a>
            . Files are processed through distributed blockchain consensus. Do
            not upload sensitive personal information.
          </p>
        </div>
      </div>
    </div>
  );
}
