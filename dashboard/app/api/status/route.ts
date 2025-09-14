import { NextRequest, NextResponse } from "next/server";

export async function GET(request: NextRequest) {
  try {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:7000";

    const response = await fetch(`${apiUrl}/api/blockchain/status`, {
      headers: { "Content-Type": "application/json" },
    });

    if (!response.ok) {
      throw new Error(`Backend error: ${response.statusText}`);
    }

    const status = await response.json();
    return NextResponse.json(status);
  } catch (error) {
    console.error("Status API error:", error);

    // Fallback when backend is unavailable
    return NextResponse.json({
      node_id: 0,
      is_primary: false,
      total_nodes: 4,
      blockchain_files: 0,
      pending_uploads: 0,
      consensus_round: 0,
      timestamp: Date.now(),
      status: "offline",
    });
  }
}
