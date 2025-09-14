import { NextRequest, NextResponse } from "next/server";

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const file = formData.get("file") as File;

    if (!file) {
      return NextResponse.json({ error: "No file provided" }, { status: 400 });
    }

    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:7000";

    console.log(`🚀 Starting blockchain upload for: ${file.name}`);

    // Forward to backend API (complete blockchain workflow)
    const backendFormData = new FormData();
    backendFormData.append("file", file);

    const response = await fetch(`${apiUrl}/api/upload`, {
      method: "POST",
      body: backendFormData,
    });

    if (!response.ok) {
      throw new Error(`Backend error: ${response.statusText}`);
    }

    const result = await response.json();

    // Enhanced response with blockchain status
    if (result.success && result.consensus_status === "committed") {
      console.log(`✅ File successfully added to blockchain: ${file.name}`);
    } else if (result.success === false && result.consensus_status === "timeout") {
      console.log(`⏰ Blockchain consensus timeout: ${file.name}`);
    }

    return NextResponse.json(result);
  } catch (error) {
    console.error("❌ Blockchain upload route error:", error);
    return NextResponse.json({ error: "Blockchain upload failed" }, { status: 500 });
  }
}