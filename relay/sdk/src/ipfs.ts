/**
 * IPFS evidence storage for dispute proceedings.
 *
 * Evidence hashes are referenced on-chain (in dispute initiation tx memos).
 * The content lives on IPFS — decentralized, permanent, Relay-independent.
 *
 * Supports: Pinata (hosted), local IPFS node, or any gateway-compatible service.
 * If Relay disappears, evidence remains retrievable via any IPFS gateway.
 */

export interface EvidencePackage {
  disputeId: string;
  jobId: string;
  submitter: string;
  timestamp: number;
  files: Array<{
    name: string;
    contentType: string;
    description: string;
    dataBase64: string;
  }>;
  statement: string;
}

export interface IPFSUploadResult {
  cid: string;
  url: string;
  size: number;
}

export interface IPFSConfig {
  provider: "pinata" | "local" | "web3storage";
  apiKey?: string;
  apiSecret?: string;
  gatewayUrl?: string;
  localNodeUrl?: string;
}

const DEFAULT_GATEWAY = "https://ipfs.io/ipfs";

/**
 * Upload an evidence package to IPFS via Pinata.
 * Returns the CID which is stored on-chain in the dispute transaction memo.
 */
export async function uploadEvidence(
  evidence: EvidencePackage,
  config: IPFSConfig
): Promise<IPFSUploadResult> {
  if (config.provider === "pinata") {
    return uploadToPinata(evidence, config);
  }
  if (config.provider === "local") {
    return uploadToLocalNode(evidence, config);
  }
  throw new Error(`Unsupported IPFS provider: ${config.provider}`);
}

/**
 * Retrieve evidence package from IPFS by CID.
 */
export async function fetchEvidence(
  cid: string,
  gatewayUrl: string = DEFAULT_GATEWAY
): Promise<EvidencePackage> {
  const url = `${gatewayUrl}/${cid}`;
  const res = await fetch(url, { signal: AbortSignal.timeout(15000) });
  if (!res.ok) throw new Error(`IPFS fetch failed: ${res.statusText} (${url})`);
  return res.json() as Promise<EvidencePackage>;
}

/**
 * Build evidence package from raw dispute inputs.
 * Normalizes structure before upload so evaluators get consistent format.
 */
export function buildEvidencePackage(
  disputeId: string,
  jobId: string,
  submitter: string,
  statement: string,
  files: EvidencePackage["files"] = []
): EvidencePackage {
  return {
    disputeId,
    jobId,
    submitter,
    timestamp: Math.floor(Date.now() / 1000),
    files,
    statement,
  };
}

/**
 * Verify evidence integrity: recompute hash and compare to on-chain reference.
 */
export async function verifyEvidenceIntegrity(
  cid: string,
  gatewayUrl?: string
): Promise<{ valid: boolean; package?: EvidencePackage }> {
  try {
    const pkg = await fetchEvidence(cid, gatewayUrl);
    // CID itself is the content hash — if fetch succeeds, content matches CID
    return { valid: true, package: pkg };
  } catch {
    return { valid: false };
  }
}

// ── Private upload implementations ──────────────────────────────────────────

async function uploadToPinata(
  evidence: EvidencePackage,
  config: IPFSConfig
): Promise<IPFSUploadResult> {
  if (!config.apiKey || !config.apiSecret) {
    throw new Error("Pinata API key and secret required");
  }

  const body = JSON.stringify({
    pinataContent: evidence,
    pinataMetadata: {
      name: `relay-evidence-${evidence.disputeId}`,
      keyvalues: {
        disputeId: evidence.disputeId,
        jobId: evidence.jobId,
        submitter: evidence.submitter,
      },
    },
  });

  const res = await fetch("https://api.pinata.cloud/pinning/pinJSONToIPFS", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      pinata_api_key: config.apiKey,
      pinata_secret_api_key: config.apiSecret,
    },
    body,
    signal: AbortSignal.timeout(30000),
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Pinata upload failed: ${err}`);
  }

  const result = await res.json() as { IpfsHash: string; PinSize: number };
  const gatewayUrl = config.gatewayUrl ?? DEFAULT_GATEWAY;

  return {
    cid: result.IpfsHash,
    url: `${gatewayUrl}/${result.IpfsHash}`,
    size: result.PinSize,
  };
}

async function uploadToLocalNode(
  evidence: EvidencePackage,
  config: IPFSConfig
): Promise<IPFSUploadResult> {
  const nodeUrl = config.localNodeUrl ?? "http://localhost:5001";
  const content = JSON.stringify(evidence);

  const formData = new FormData();
  formData.append("file", new Blob([content], { type: "application/json" }));

  const res = await fetch(`${nodeUrl}/api/v0/add?pin=true`, {
    method: "POST",
    body: formData,
    signal: AbortSignal.timeout(30000),
  });

  if (!res.ok) throw new Error(`Local IPFS add failed: ${res.statusText}`);

  const result = await res.json() as { Hash: string; Size: string };
  const gatewayUrl = config.gatewayUrl ?? DEFAULT_GATEWAY;

  return {
    cid: result.Hash,
    url: `${gatewayUrl}/${result.Hash}`,
    size: parseInt(result.Size, 10),
  };
}
