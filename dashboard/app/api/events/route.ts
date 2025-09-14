import { NextRequest, NextResponse } from "next/server";

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const limit = searchParams.get("limit") || "50";

    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:7000";

    const response = await fetch(`${apiUrl}/api/events?limit=${limit}`, {
      headers: { "Content-Type": "application/json" },
    });

    if (!response.ok) {
      throw new Error(`Backend error: ${response.statusText}`);
    }

    const events = await response.json();
    return NextResponse.json(events);
  } catch (error) {
    console.error("Events API error:", error);

    // Fallback mock data for development
    const mockEvents = [
      {
        id: 1,
        merkle_root: "abc123def456...",
        file_path: "test-document.pdf",
        file_hash: "sha512hash...",
        node_id: 0,
        consensus_round: 1,
        status: "committed",
        timestamp: new Date().toISOString(),
        created_at: new Date().toISOString(),
      },
    ];

    return NextResponse.json(mockEvents);
  }
}
