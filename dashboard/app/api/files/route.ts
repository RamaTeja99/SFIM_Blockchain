import { NextRequest, NextResponse } from 'next/server';

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = searchParams.get('limit') || '50';
    
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:7000';
    
    const response = await fetch(`${apiUrl}/api/files?limit=${limit}`, {
      headers: { 'Content-Type': 'application/json' }
    });
    
    if (!response.ok) {
      throw new Error(`Backend error: ${response.statusText}`);
    }
    
    const files = await response.json();
    return NextResponse.json(files);
    
  } catch (error) {
    console.error('Files API error:', error);
    return NextResponse.json(
      { error: 'Failed to fetch files' }, 
      { status: 500 }
    );
  }
}
