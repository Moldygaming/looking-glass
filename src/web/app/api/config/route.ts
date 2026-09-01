import { NextResponse } from "next/server";

export function GET() {
  return NextResponse.json({
    entra: Boolean(
      process.env.AUTH_MICROSOFT_ENTRA_ID_ID && process.env.AUTH_MICROSOFT_ENTRA_ID_TENANT_ID
    ),
  });
}
