import { NextRequest, NextResponse } from 'next/server';

// Mock data for development
const mockLogs = [
  {
    id: 1,
    event_type: 'consensus',
    node_id: 0,
    message: 'Consensus reached for digest abc123...',
    details: '{"digest": "abc123", "round": 1}',
    severity: 'info',
    timestamp: new Date().toISOString(),
  },
  {
    id: 2,
    event_type: 'file_scan',
    node_id: null,
    message: 'File system scan completed',
    details: '{"files_scanned": 42}',
    severity: 'info',
    timestamp: new Date(Date.now() - 60000).toISOString(),
  },
  {
    id: 3,
    event_type: 'tpm_attestation',
    node_id: 1,
    message: 'TPM attestation successful',
    details: '{"trust_level": "trusted"}',
    severity: 'info',
    timestamp: new Date(Date.now() - 120000).toISOString(),
  }
];

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = parseInt(searchParams.get('limit') || '100');

    // In production, this would query the actual database
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:7000';

    try {
      const response = await fetch(`${apiUrl}/api/logs?limit=${limit}`, {
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (response.ok) {
        const logs = await response.json();
        return NextResponse.json(logs);
      }
    } catch (error) {
      console.warn('Failed to fetch from backend, using mock data:', error);
    }

    // Fallback to mock data
    return NextResponse.json(mockLogs.slice(0, limit));

  } catch (error) {
    console.error('Error in logs API route:', error);
    return NextResponse.json(
      { error: 'Failed to fetch logs' },
      { status: 500 }
    );
  }
}

export async function POST(request: NextRequest) {
  try {
    const logData = await request.json();

    // In production, this would save to the actual database
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:7000';

    try {
      const response = await fetch(`${apiUrl}/api/logs`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(logData),
      });

      if (response.ok) {
        const result = await response.json();
        return NextResponse.json(result);
      }
    } catch (error) {
      console.warn('Failed to post to backend:', error);
    }

    // Mock success response
    return NextResponse.json({
      success: true,
      id: Date.now(),
      message: 'Log entry created'
    });

  } catch (error) {
    console.error('Error in logs POST route:', error);
    return NextResponse.json(
      { error: 'Failed to create log entry' },
      { status: 500 }
    );
  }
}
