import { NextRequest, NextResponse } from "next/server";
import crypto from "crypto";

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const file = formData.get("file") as File;

    if (!file) {
      return NextResponse.json({ error: "No file provided" }, { status: 400 });
    }

    // Read file content
    const buffer = Buffer.from(await file.arrayBuffer());

    // Calculate SHA-512 hash
    const hash = crypto.createHash("sha512").update(buffer).digest("hex");

    console.log(
      `🔍 Verifying blockchain integrity for: ${file.name} (${hash.substring(
        0,
        16
      )}...)`
    );

    // Submit to backend for blockchain verification
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:7000";

    try {
      const response = await fetch(`${apiUrl}/api/verify`, {
        method: "POST",
        body: formData,
      });

      if (response.ok) {
        const result = await response.json();

        // Log verification result
        if (result.valid && result.blockchain_status?.includes("BLOCKCHAIN")) {
          console.log(`✅ File verified on blockchain: ${file.name}`);
        } else if (result.blockchain_status?.includes("PENDING")) {
          console.log(`🟡 File pending blockchain consensus: ${file.name}`);
        } else {
          console.log(`❌ File not found on blockchain: ${file.name}`);
        }

        return NextResponse.json(result);
      } else {
        throw new Error(`Backend error: ${response.statusText}`);
      }
    } catch (error) {
      console.warn(
        "Failed to verify with blockchain backend, using fallback:",
        error
      );

      // Fallback response when backend is unavailable
      const mockResponse = {
        valid: false,
        message: "❌ Backend unavailable - blockchain verification failed",
        blockchain_status: "🔴 BACKEND_UNAVAILABLE",
        log: {
          id: crypto.randomUUID(),
          fileName: file.name,
          file_hash: hash,
          status: "backend_unavailable" as const,
          timestamp: new Date().toISOString(),
          merkle_root: null,
          node_id: null,
          consensus_round: 0,
          verification_result: "BACKEND_UNAVAILABLE",
        },
      };
      return NextResponse.json(mockResponse);
    }
  } catch (error) {
    console.error("Error in blockchain verify route:", error);
    return NextResponse.json(
      { error: "Blockchain file verification failed" },
      { status: 500 }
    );
  }
}
