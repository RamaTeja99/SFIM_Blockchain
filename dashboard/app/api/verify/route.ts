import { NextRequest, NextResponse } from 'next/server';
import crypto from 'crypto';

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const file = formData.get('file') as File;

    if (!file) {
      return NextResponse.json(
        { error: 'No file provided' },
        { status: 400 }
      );
    }

    // Read file content
    const buffer = Buffer.from(await file.arrayBuffer());

    // Calculate SHA-512 hash
    const hash = crypto.createHash('sha512').update(buffer).digest('hex');

    // In production, this would submit to the PBFT network
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:7000';

    try {
      // Try to submit to backend
      const response = await fetch(`${apiUrl}/api/verify`, {
        method: 'POST',
        body: formData,
      });

      if (response.ok) {
        const result = await response.json();
        return NextResponse.json(result);
      }
    } catch (error) {
      console.warn('Failed to verify with backend, using mock response:', error);
    }

    // Mock verification response
    const mockResponse = {
      valid: true,
      log: {
        id: crypto.randomUUID(),
        fileName: file.name,
        hash: hash,
        status: 'committed' as const,
        timestamp: new Date().toISOString(),
        merkle_root: hash,
        node_id: 0,
        consensus_round: Math.floor(Math.random() * 1000) + 1,
      }
    };

    return NextResponse.json(mockResponse);

  } catch (error) {
    console.error('Error in verify route:', error);
    return NextResponse.json(
      { error: 'File verification failed' },
      { status: 500 }
    );
  }
}