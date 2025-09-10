'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  ChartBarIcon,
  ShieldCheckIcon,
  ComputerDesktopIcon,
  ClockIcon,
  ExclamationTriangleIcon,
  CheckCircleIcon,
  XCircleIcon,
  BellIcon
} from '@heroicons/react/24/outline';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  Legend
} from 'recharts';

// Types
interface IntegrityEvent {
  id: number;
  merkle_root: string;
  file_path?: string;
  file_hash?: string;
  bls_signature?: string;
  node_id: number;
  consensus_round: number;
  status: 'pending' | 'committed' | 'rejected';
  timestamp: string;
  created_at: string;
}

interface TPMQuote {
  id: number;
  node_id: number;
  nonce: string;
  is_valid: boolean;
  trust_level: 'trusted' | 'suspicious' | 'untrusted';
  timestamp: string;
  created_at: string;
}

interface NodeInfo {
  node_id: number;
  is_primary: boolean;
  total_nodes: number;
  connected_peers: number;
  database_url: string;
  use_simulated_tpm: boolean;
  timestamp: number;
}

interface SystemMetrics {
  consensus_latency: number;
  throughput: number;
  detection_rate: number;
  trusted_nodes: number;
  total_events: number;
}

// Components
function StatusBadge({ status }: { status: string }) {
  const getStatusStyle = (status: string) => {
    switch (status.toLowerCase()) {
      case 'committed':
      case 'trusted':
      case 'active':
        return 'badge-success';
      case 'pending':
      case 'suspicious':
        return 'badge-warning';
      case 'rejected':
      case 'untrusted':
      case 'inactive':
        return 'badge-danger';
      default:
        return 'badge-primary';
    }
  };

  return (
    <span className={`badge ${getStatusStyle(status)}`}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

function MetricCard({
  title,
  value,
  icon: Icon,
  trend,
  color = 'primary'
}: {
  title: string;
  value: string | number;
  icon: any;
  trend?: number;
  color?: string;
}) {
  const colorClasses = {
    primary: 'text-primary-600 bg-primary-100',
    success: 'text-success-600 bg-success-100',
    warning: 'text-warning-600 bg-warning-100',
    danger: 'text-danger-600 bg-danger-100',
  };

  return (
    <div className="card">
      <div className="card-body">
        <div className="flex items-center">
          <div className={`p-3 rounded-lg ${colorClasses[color as keyof typeof colorClasses]}`}>
            <Icon className="h-6 w-6" />
          </div>
          <div className="ml-4 flex-1">
            <p className="text-sm font-medium text-gray-500">{title}</p>
            <div className="flex items-center">
              <p className="text-2xl font-semibold text-gray-900">{value}</p>
              {trend !== undefined && (
                <span className={`ml-2 text-sm ${trend >= 0 ? 'text-success-600' : 'text-danger-600'}`}>
                  {trend >= 0 ? '↗' : '↘'} {Math.abs(trend)}%
                </span>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ConnectionIndicator({ isConnected }: { isConnected: boolean }) {
  return (
    <div className="flex items-center space-x-2">
      <div className={`w-3 h-3 rounded-full ${isConnected ? 'bg-success-500 pulse-ring' : 'bg-danger-500'}`} />
      <span className={`text-sm font-medium ${isConnected ? 'text-success-600' : 'text-danger-600'}`}>
        {isConnected ? 'Connected' : 'Disconnected'}
      </span>
    </div>
  );
}

// Main Dashboard Component
export default function Dashboard() {
  // State
  const [events, setEvents] = useState<IntegrityEvent[]>([]);
  const [quotes, setQuotes] = useState<TPMQuote[]>([]);
  const [nodeInfo, setNodeInfo] = useState<NodeInfo | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  // WebSocket connection
  const connectWebSocket = useCallback(() => {
    const wsUrl = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:7000/feed';
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      setIsConnected(true);
      console.log('WebSocket connected');
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'feed_update') {
          setEvents(data.events || []);
          setQuotes(data.quotes || []);
          setLastUpdate(new Date());
          setLoading(false);
        }
      } catch (error) {
        console.error('Error parsing WebSocket message:', error);
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
      console.log('WebSocket disconnected, attempting reconnect...');
      // Reconnect after 5 seconds
      setTimeout(connectWebSocket, 5000);
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      setIsConnected(false);
    };

    return ws;
  }, []);

  // Fetch node status
  const fetchNodeStatus = useCallback(async () => {
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:7000';
      const response = await fetch(`${apiUrl}/api/status`);
      if (response.ok) {
        const status = await response.json();
        setNodeInfo(status);
      }
    } catch (error) {
      console.error('Error fetching node status:', error);
    }
  }, []);

  // Effects
  useEffect(() => {
    const ws = connectWebSocket();
    fetchNodeStatus();

    // Refresh node status every 30 seconds
    const statusInterval = setInterval(fetchNodeStatus, 30000);

    return () => {
      ws.close();
      clearInterval(statusInterval);
    };
  }, [connectWebSocket, fetchNodeStatus]);

  // Computed values
  const metrics: SystemMetrics = {
    consensus_latency: events.length > 0 ? 0.75 : 0, // Mock average latency
    throughput: events.length > 0 ? Math.round(events.length / 60) : 0, // Events per minute
    detection_rate: 98.6, // Mock detection rate
    trusted_nodes: quotes.filter(q => q.trust_level === 'trusted').length,
    total_events: events.length,
  };

  const chartData = events.slice(0, 20).reverse().map((event, index) => ({
    round: event.consensus_round,
    timestamp: new Date(event.timestamp).getTime(),
    latency: 0.5 + Math.random() * 0.8, // Mock latency data
  }));

  const trustLevelData = [
    { name: 'Trusted', value: quotes.filter(q => q.trust_level === 'trusted').length, color: '#22c55e' },
    { name: 'Suspicious', value: quotes.filter(q => q.trust_level === 'suspicious').length, color: '#f59e0b' },
    { name: 'Untrusted', value: quotes.filter(q => q.trust_level === 'untrusted').length, color: '#ef4444' },
  ];

  const statusCounts = {
    committed: events.filter(e => e.status === 'committed').length,
    pending: events.filter(e => e.status === 'pending').length,
    rejected: events.filter(e => e.status === 'rejected').length,
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-32 w-32 border-b-2 border-primary-600 mx-auto mb-4"></div>
          <p className="text-lg text-gray-600">Loading SFIM Dashboard...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center">
              <ShieldCheckIcon className="h-8 w-8 text-primary-600 mr-3" />
              <div>
                <h1 className="text-2xl font-bold text-gray-900">SFIM Dashboard</h1>
                <p className="text-sm text-gray-500">Secure File Integrity Monitoring</p>
              </div>
            </div>
            <div className="flex items-center space-x-4">
              <ConnectionIndicator isConnected={isConnected} />
              {lastUpdate && (
                <div className="text-sm text-gray-500">
                  Last update: {lastUpdate.toLocaleTimeString()}
                </div>
              )}
              {nodeInfo && (
                <div className="flex items-center space-x-2">
                  <ComputerDesktopIcon className="h-5 w-5 text-gray-400" />
                  <span className="text-sm text-gray-600">Node {nodeInfo.node_id}</span>
                  {nodeInfo.is_primary && (
                    <span className="badge badge-primary">Primary</span>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8">
        {/* Metrics Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          <MetricCard
            title="Total Events"
            value={metrics.total_events}
            icon={ChartBarIcon}
            color="primary"
          />
          <MetricCard
            title="Consensus Latency"
            value={`${metrics.consensus_latency}s`}
            icon={ClockIcon}
            color="success"
            trend={-5.2}
          />
          <MetricCard
            title="Detection Rate"
            value={`${metrics.detection_rate}%`}
            icon={ShieldCheckIcon}
            color="success"
          />
          <MetricCard
            title="Trusted Nodes"
            value={`${metrics.trusted_nodes}/${nodeInfo?.total_nodes || 4}`}
            icon={ComputerDesktopIcon}
            color="primary"
          />
        </div>

        {/* Status Overview */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
          {/* Consensus Status */}
          <div className="card">
            <div className="card-header">
              <h3 className="text-lg font-medium text-gray-900 flex items-center">
                <CheckCircleIcon className="h-5 w-5 text-success-500 mr-2" />
                Consensus Status
              </h3>
            </div>
            <div className="card-body">
              <div className="space-y-3">
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-600">Committed</span>
                  <span className="badge badge-success">{statusCounts.committed}</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-600">Pending</span>
                  <span className="badge badge-warning">{statusCounts.pending}</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-600">Rejected</span>
                  <span className="badge badge-danger">{statusCounts.rejected}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Node Trust Levels */}
          <div className="card">
            <div className="card-header">
              <h3 className="text-lg font-medium text-gray-900 flex items-center">
                <ShieldCheckIcon className="h-5 w-5 text-primary-500 mr-2" />
                Node Trust Levels
              </h3>
            </div>
            <div className="card-body">
              {trustLevelData.length > 0 ? (
                <ResponsiveContainer width="100%" height={150}>
                  <PieChart>
                    <Pie
                      data={trustLevelData}
                      cx="50%"
                      cy="50%"
                      innerRadius={30}
                      outerRadius={60}
                      paddingAngle={5}
                      dataKey="value"
                    >
                      {trustLevelData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-gray-500 text-center py-8">No trust data available</p>
              )}
            </div>
          </div>

          {/* System Health */}
          <div className="card">
            <div className="card-header">
              <h3 className="text-lg font-medium text-gray-900 flex items-center">
                <ExclamationTriangleIcon className="h-5 w-5 text-warning-500 mr-2" />
                System Health
              </h3>
            </div>
            <div className="card-body">
              <div className="space-y-3">
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-600">WebSocket</span>
                  <StatusBadge status={isConnected ? 'Connected' : 'Disconnected'} />
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-600">Database</span>
                  <StatusBadge status="Active" />
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-600">TPM</span>
                  <StatusBadge status={nodeInfo?.use_simulated_tpm ? 'Simulated' : 'Hardware'} />
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-600">Consensus</span>
                  <StatusBadge status="Active" />
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Charts */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
          {/* Consensus Latency Chart */}
          <div className="card">
            <div className="card-header">
              <h3 className="text-lg font-medium text-gray-900">Consensus Latency</h3>
              <p className="text-sm text-gray-500">Recent consensus round latencies</p>
            </div>
            <div className="card-body">
              <div className="h-64">
                {chartData.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData}>
                      <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
                      <XAxis
                        dataKey="round"
                        className="text-xs"
                      />
                      <YAxis
                        className="text-xs"
                        label={{ value: 'Latency (s)', angle: -90, position: 'insideLeft' }}
                      />
                      <Tooltip
                        formatter={(value) => [`${Number(value).toFixed(3)}s`, 'Latency']}
                        labelFormatter={(label) => `Round ${label}`}
                      />
                      <Line
                        type="monotone"
                        dataKey="latency"
                        stroke="#3b82f6"
                        strokeWidth={2}
                        dot={{ r: 3 }}
                        activeDot={{ r: 5 }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex items-center justify-center h-full">
                    <p className="text-gray-500">No consensus data available</p>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Event Timeline */}
          <div className="card">
            <div className="card-header">
              <h3 className="text-lg font-medium text-gray-900">Event Timeline</h3>
              <p className="text-sm text-gray-500">Recent integrity events</p>
            </div>
            <div className="card-body">
              <div className="h-64">
                {events.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chartData}>
                      <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
                      <XAxis
                        dataKey="round"
                        className="text-xs"
                      />
                      <YAxis
                        className="text-xs"
                        label={{ value: 'Round', angle: -90, position: 'insideLeft' }}
                      />
                      <Tooltip
                        formatter={(value) => [value, 'Round']}
                      />
                      <Bar
                        dataKey="round"
                        fill="#3b82f6"
                        radius={[2, 2, 0, 0]}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex items-center justify-center h-full">
                    <p className="text-gray-500">No event data available</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Recent Events Table */}
        <div className="card">
          <div className="card-header">
            <h3 className="text-lg font-medium text-gray-900">Recent Integrity Events</h3>
            <p className="text-sm text-gray-500">Latest file integrity monitoring events</p>
          </div>
          <div className="overflow-hidden">
            {events.length > 0 ? (
              <div className="overflow-x-auto custom-scrollbar">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Merkle Root
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Node
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Round
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Status
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Timestamp
                      </th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {events.slice(0, 10).map((event) => (
                      <tr key={event.id} className="hover:bg-gray-50">
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="text-sm font-mono text-gray-900">
                            {event.merkle_root.substring(0, 16)}...
                          </div>
                          {event.file_path && (
                            <div className="text-xs text-gray-500">{event.file_path}</div>
                          )}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="flex items-center">
                            <ComputerDesktopIcon className="h-4 w-4 text-gray-400 mr-1" />
                            <span className="text-sm text-gray-900">{event.node_id}</span>
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                          {event.consensus_round}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <StatusBadge status={event.status} />
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                          {new Date(event.timestamp).toLocaleString()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="p-12 text-center">
                <ChartBarIcon className="mx-auto h-12 w-12 text-gray-400" />
                <h3 className="mt-2 text-sm font-medium text-gray-900">No events yet</h3>
                <p className="mt-1 text-sm text-gray-500">
                  Start monitoring files to see integrity events here.
                </p>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
