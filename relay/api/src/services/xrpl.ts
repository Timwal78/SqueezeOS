/**
 * Thin wrapper over xrpl.js for the API server.
 * The server only READS from XRPL (verification).
 * It NEVER signs transactions or submits on behalf of users.
 */

import { Client } from "xrpl";
import { Network } from "../../../sdk/src/types";
import { XRPL_NODES } from "../../../sdk/src/constants";
import { PaymentChannelInfo } from "../../../sdk/src/types";

const clients = new Map<Network, Client>();

async function getClient(network: Network): Promise<Client> {
  const existing = clients.get(network);
  if (existing?.isConnected()) return existing;
  const client = new Client(XRPL_NODES[network]);
  await client.connect();
  clients.set(network, client);
  return client;
}

export async function getChannelInfo(
  network: string,
  channelId: string
): Promise<PaymentChannelInfo | null> {
  const net = network as Network;
  const client = await getClient(net);

  try {
    const response = await client.request({
      command: "ledger_entry",
      payment_channel: channelId,
      ledger_index: "validated",
    });

    const node = (response.result as { node?: Record<string, unknown> }).node;
    if (!node) return null;

    return {
      channelId,
      account: node.Account as string,
      destination: node.Destination as string,
      amount: node.Amount as string,
      balance: node.Balance as string,
      settleDelay: node.SettleDelay as number,
      publicKey: node.PublicKey as string,
      expiration: node.Expiration as number | undefined,
      destinationTag: node.DestinationTag as number | undefined,
    };
  } catch {
    return null;
  }
}

export async function verifyTxOnChain(
  network: string,
  txHash: string
): Promise<boolean> {
  const net = network as Network;
  const client = await getClient(net);

  try {
    const response = await client.request({
      command: "tx",
      transaction: txHash,
    });
    const result = (response.result as { meta?: { TransactionResult?: string } })
      .meta?.TransactionResult;
    return result === "tesSUCCESS";
  } catch {
    return false;
  }
}
