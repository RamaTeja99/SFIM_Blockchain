"use client"

import { useState, useEffect, useCallback } from 'react';

interface UploadResult {
  success?: boolean;
  message?: string;
  file_hash?: string;
  merkle_root?: string;
  trust_level?: string;
  consensus_status?: string;
  consensus_round?: number;
  blockchain_status?: string;
  error?: string;
}

interface VerifyResult {
  valid: boolean;
  message: string;
  blockchain_status?: string;
  log?: {
    id?: string;
    fileName?: string;
    file_hash?: string;
    status?: string;
    timestamp?: string;
    merkle_root?: string;
    node_id?: number;
    consensus_round?: number;
    trust_level?: string;
    verification_result?: string;
  };
  error?: string;
}

interface BlockchainEvent {
  id: number;
  merkle_root: string;
  file_path?: string;
  file_hash?: string;
  node_id: number;
  consensus_round: number;
  status: string;
  timestamp: string;
  created_at: string;
}

interface SystemStatus {
  node_id: number;
  is_primary: boolean;
  total_nodes: number;
  blockchain_files: number;
  pending_uploads: number;
  consensus_round: number;
  timestamp: number;
}

export default function BlockchainFileIntegrity() {
  const [activeTab, setActiveTab] = useState<'upload' | 'verify'>('upload');
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isVerifying, setIsVerifying] = useState(false);
  const [events, setEvents] = useState<BlockchainEvent[]>([]);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [connectionStatus, setConnectionStatus] = useState<'online' | 'offline'>('offline');

  const fetchEvents = useCallback(async () => {
    try {
      const response = await fetch('/api/events?limit=10');
      if (response.ok) {
        const data = await response.json();
        setEvents(data);
      }
    } catch (error) {
      console.error('Failed to fetch events:', error);
    }
  }, []);

  const fetchSystemStatus = useCallback(async () => {
    try {
      const response = await fetch('/api/status');
      if (response.ok) {
        const data = await response.json();
        setSystemStatus(data);
        setConnectionStatus('online');
      } else {
        setConnectionStatus('offline');
      }
    } catch (error) {
      console.error('Failed to fetch system status:', error);
      setConnectionStatus('offline');
    }
  }, []);

  useEffect(() => {
    fetchEvents();
    fetchSystemStatus();
    
    const interval = setInterval(() => {
      fetchEvents();
      fetchSystemStatus();
    }, 5000); // Update every 5 seconds

    return () => clearInterval(interval);
  }, [fetchEvents, fetchSystemStatus]);

  const handleUpload = async (file: File) => {
    setIsUploading(true);
    setUploadResult(null);
    
    try {
      console.log(`🚀 Starting blockchain upload workflow for: ${file.name}`);
      
      const formData = new FormData();
      formData.append('file', file);
      
      const response = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
      });
      
      const result = await response.json();
      setUploadResult(result);
      
      if (result.success && result.consensus_status === 'committed') {
        console.log('✅ File successfully added to blockchain');
        fetchEvents(); // Refresh events
      } else if (result.consensus_status === 'timeout') {
        console.log('⏰ Blockchain consensus timeout - file may be added later');
      }
      
    } catch (error) {
      console.error('❌ Upload error:', error);
      setUploadResult({
        success: false,
        error: 'Upload failed',
        blockchain_status: '🔴 UPLOAD_FAILED'
      });
    } finally {
      setIsUploading(false);
    }
  };

  const handleVerify = async (file: File) => {
    setIsVerifying(true);
    setVerifyResult(null);
    
    try {
      console.log(`🔍 Verifying blockchain integrity for: ${file.name}`);
      
      const formData = new FormData();
      formData.append('file', file);
      
      const response = await fetch('/api/verify', {
        method: 'POST',
        body: formData,
      });
      
      const result = await response.json();
      setVerifyResult(result);
      
    } catch (error) {
      console.error('❌ Verify error:', error);
      setVerifyResult({
        valid: false,
        message: 'Verification failed',
        blockchain_status: '🔴 VERIFY_FAILED'
      });
    } finally {
      setIsVerifying(false);
    }
  };

  const getStatusBadgeStyle = (status: string) => {
    switch (status) {
      case 'committed':
        return 'desktop-badge committed';
      case 'pending':
        return 'desktop-badge pending';
      default:
        return 'desktop-badge rejected';
    }
  };

  const getBlockchainStatusStyle = (status?: string) => {
    if (status?.includes('✅') || status?.includes('BLOCKCHAIN')) {
      return 'text-green-600 font-semibold';
    } else if (status?.includes('🟡') || status?.includes('PENDING')) {
      return 'text-yellow-600 font-semibold';
    } else if (status?.includes('🔴') || status?.includes('NOT')) {
      return 'text-red-600 font-semibold';
    }
    return 'text-gray-600';
  };

  return (
    <div className="desktop-wrapper">
      <div className="desktop-header">
        <h1 className="desktop-logo">🔗 BlockchainVerify</h1>
        <p className="desktop-subtitle">
          Distributed File Integrity Verification with Blockchain Consensus
        </p>
        
        {/* System Status */}
        <div className="desktop-connection">
          <div className="desktop-connection-status">
            <div className={`desktop-connection-dot ${connectionStatus}`}></div>
            <span>
              {connectionStatus === 'online' 
                ? `Node ${systemStatus?.node_id} • ${systemStatus?.total_nodes} Nodes • Round ${systemStatus?.consensus_round}`
                : 'Disconnected'
              }
            </span>
          </div>
          
          {systemStatus && (
            <div className="text-sm text-gray-600">
              📊 Blockchain Files: {systemStatus.blockchain_files} | 
              ⏳ Pending: {systemStatus.pending_uploads} |
              {systemStatus.is_primary ? ' 👑 Primary Node' : ' 🔗 Peer Node'}
            </div>
          )}
        </div>
      </div>

      {/* Workflow Information */}
      <div className="mb-8 p-6 bg-blue-50 rounded-lg border border-blue-200">
        <h3 className="text-lg font-semibold mb-3 text-blue-900">🔗 Blockchain Workflow</h3>
        <div className="text-sm text-blue-800 space-y-2">
          <div><strong>1. Upload:</strong> File Scanner → SHA-512 → TPM Quote → Peer Validation → Merkle Tree → PBFT Consensus → Blockchain</div>
          <div><strong>2. Verify:</strong> Check file integrity against distributed blockchain ledger with consensus verification</div>
        </div>
      </div>

      <div className="desktop-tabs">
        <button
          className={`desktop-tab ${activeTab === 'upload' ? 'active' : ''}`}
          onClick={() => setActiveTab('upload')}
        >
          📤 Add to Blockchain
        </button>
        <button
          className={`desktop-tab ${activeTab === 'verify' ? 'active' : ''}`}
          onClick={() => setActiveTab('verify')}
        >
          🔍 Verify from Blockchain
        </button>
      </div>

      <div className="desktop-main">
        {activeTab === 'upload' && (
          <div className="desktop-upload-area">
            <div className="desktop-upload-icon">📤</div>
            <div className="desktop-upload-text">Add File to Blockchain</div>
            <div className="desktop-upload-subtext">
              Upload a file to add it to the distributed blockchain ledger with PBFT consensus
            </div>
            <input
              className="desktop-file-input"
              type="file"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleUpload(file);
              }}
              disabled={isUploading}
            />
            <button className="desktop-upload-button" disabled={isUploading}>
              {isUploading ? (
                <>
                  <span className="desktop-spinner"></span>
                  Processing Blockchain Workflow...
                </>
              ) : (
                'Select File to Upload'
              )}
            </button>
          </div>
        )}

        {activeTab === 'verify' && (
          <div className="desktop-upload-area">
            <div className="desktop-upload-icon">🔍</div>
            <div className="desktop-upload-text">Verify File Integrity</div>
            <div className="desktop-upload-subtext">
              Check if your file exists on the blockchain and verify its integrity
            </div>
            <input
              className="desktop-file-input"
              type="file"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleVerify(file);
              }}
              disabled={isVerifying}
            />
            <button className="desktop-upload-button" disabled={isVerifying}>
              {isVerifying ? (
                <>
                  <span className="desktop-spinner"></span>
                  Verifying with Blockchain...
                </>
              ) : (
                'Select File to Verify'
              )}
            </button>
          </div>
        )}

        {/* Upload Results */}
        {uploadResult && (
          <div className={`desktop-result ${uploadResult.success ? 'success' : 'error'}`}>
            <div className="desktop-result-title">
              {uploadResult.success ? '✅ Blockchain Upload Result' : '❌ Upload Failed'}
            </div>
            <div className="desktop-result-content">
              <p><strong>Status:</strong> 
                <span className={getBlockchainStatusStyle(uploadResult.blockchain_status)}>
                  {uploadResult.blockchain_status || 'Unknown'}
                </span>
              </p>
              <p>{uploadResult.message}</p>
              {uploadResult.error && (
                <p className="text-red-600">❌ {uploadResult.error}</p>
              )}
              {uploadResult.success && uploadResult.file_hash && (
                <div className="mt-3 space-y-1">
                  <p><strong>File Hash:</strong> {uploadResult.file_hash.substring(0, 32)}...</p>
                  <p><strong>Merkle Root:</strong> {uploadResult.merkle_root?.substring(0, 32)}...</p>
                  <p><strong>Consensus Round:</strong> {uploadResult.consensus_round}</p>
                  <p><strong>Trust Level:</strong> {uploadResult.trust_level}</p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Verify Results */}
        {verifyResult && (
          <div className={`desktop-result ${verifyResult.valid ? 'success' : 'error'}`}>
            <div className="desktop-result-title">
              {verifyResult.valid ? '✅ Blockchain Verification Result' : '❌ Verification Failed'}
            </div>
            <div className="desktop-result-content">
              <p><strong>Status:</strong> 
                <span className={getBlockchainStatusStyle(verifyResult.blockchain_status)}>
                  {verifyResult.blockchain_status || 'Unknown'}
                </span>
              </p>
              <p>{verifyResult.message}</p>
              {verifyResult.valid && verifyResult.log && (
                <div className="mt-3 space-y-1">
                  <p><strong>File Hash:</strong> {verifyResult.log.file_hash?.substring(0, 32)}...</p>
                  <p><strong>Consensus Round:</strong> {verifyResult.log.consensus_round}</p>
                  <p><strong>Node ID:</strong> {verifyResult.log.node_id}</p>
                  <p><strong>Trust Level:</strong> {verifyResult.log.trust_level}</p>
                  <p><strong>Verification:</strong> {verifyResult.log.verification_result}</p>
                </div>
              )}
              {verifyResult.error && (
                <p className="text-red-600">❌ {verifyResult.error}</p>
              )}
            </div>
          </div>
        )}

        {/* System Status */}
        <div className="desktop-status-grid">
          <div className="desktop-status-card">
            <div className="desktop-status-title">📊 Blockchain Status</div>
            {systemStatus ? (
              <div className="space-y-2 text-sm">
                <div>Node ID: <strong>{systemStatus.node_id}</strong></div>
                <div>Role: <strong>{systemStatus.is_primary ? '👑 Primary' : '🔗 Peer'}</strong></div>
                <div>Total Nodes: <strong>{systemStatus.total_nodes}</strong></div>
                <div>Blockchain Files: <strong>{systemStatus.blockchain_files}</strong></div>
                <div>Pending Uploads: <strong>{systemStatus.pending_uploads}</strong></div>
                <div>Consensus Round: <strong>{systemStatus.consensus_round}</strong></div>
              </div>
            ) : (
              <p>Loading system status...</p>
            )}
          </div>
        </div>
      </div>

      {/* Recent Blockchain Events */}
      <div className="desktop-events">
        <div className="desktop-events-title">📋 Recent Blockchain Events</div>
        <div className="desktop-events-table-container">
          {events.length > 0 ? (
            <table className="desktop-events-table">
              <thead>
                <tr>
                  <th>Merkle Root</th>
                  <th>File</th>
                  <th>Node</th>
                  <th>Round</th>
                  <th>Status</th>
                  <th>Timestamp</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.id}>
                    <td>
                      <code className="desktop-hash">
                        {event.merkle_root.substring(0, 16)}...
                      </code>
                    </td>
                    <td>
                      {event.file_path && (
                        <span className="desktop-file-name">{event.file_path}</span>
                      )}
                    </td>
                    <td>{event.node_id}</td>
                    <td>{event.consensus_round}</td>
                    <td>
                      <span className={getStatusBadgeStyle(event.status)}>
                        {event.status}
                      </span>
                    </td>
                    <td>{new Date(event.timestamp).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p>Upload files to see blockchain events here</p>
          )}
        </div>
      </div>

      {/* Legal */}
      <div className="desktop-legal">
        <div className="desktop-legal-text">
          By uploading a file, you agree to our{" "}
          <a href="#" className="desktop-legal-link">Terms of Service</a>
          {" "} and{" "}
          <a href="#" className="desktop-legal-link">Privacy Policy</a>
          . Files are processed through distributed blockchain consensus with TPM attestation.
          Do not upload sensitive personal information.
        </div>
      </div>
    </div>
  );
}