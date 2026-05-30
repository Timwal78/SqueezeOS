import { EthereumProvider } from '@walletconnect/ethereum-provider'
import { BrowserProvider, formatEther, parseEther, Contract, formatUnits } from 'ethers'
import {
  WC_PROJECT_ID, RPC, BILLING_WALLET,
  CHAIN_ETH, CHAIN_BASE, CHAIN_ZKSYNC, CHAIN_HYPERLIQUID, CHAIN_ZETA,
  USDC_ADDRESS,
} from './config.js'

// Fee scales down with tier: SIGNAL 0.5% · SOVEREIGN 0.25% · INSTITUTIONAL 0.1%
function getFeeBps() {
  try { return BigInt(window.NOS?.Subscription?.getFeeBps?.() ?? 50) }
  catch { return 50n }
}

const ERC20_ABI = [
  'function balanceOf(address owner) view returns (uint256)',
  'function decimals() view returns (uint8)',
  'function symbol() view returns (string)',
  'function transfer(address to, uint256 amount) returns (bool)',
  'function allowance(address owner, address spender) view returns (uint256)',
  'function approve(address spender, uint256 amount) returns (bool)',
]

let _wc = null
let _ep = null

async function initProvider() {
  if (_wc) return _wc

  _wc = await EthereumProvider.init({
    projectId: WC_PROJECT_ID,
    chains: [CHAIN_ETH],
    optionalChains: [CHAIN_BASE, CHAIN_ZKSYNC, CHAIN_HYPERLIQUID, CHAIN_ZETA],
    showQrModal: true,
    qrModalOptions: {
      themeMode: 'dark',
      themeVariables: {
        '--wcm-accent-color': '#00dbe9',
        '--wcm-background-color': '#131315',
      },
    },
    rpcMap: RPC,
    metadata: {
      name: 'Neural_OS',
      description: 'Institutional RWA Agentic Infrastructure',
      url: 'https://neuralOS.app',
      icons: [],
    },
  })

  _wc.on('accountsChanged', (accounts) => {
    document.dispatchEvent(new CustomEvent('nos:account', { detail: { address: accounts[0] ?? null } }))
  })
  _wc.on('chainChanged', (chainId) => {
    document.dispatchEvent(new CustomEvent('nos:chain', { detail: { chainId: Number(chainId) } }))
  })
  _wc.on('disconnect', () => {
    _ep = null
    document.dispatchEvent(new CustomEvent('nos:disconnect'))
  })

  if (_wc.session) {
    _ep = new BrowserProvider(_wc)
  }

  return _wc
}

export const Wallet = {
  connect: async () => {
    const wc = await initProvider()
    await wc.connect()
    _ep = new BrowserProvider(wc)
    return wc.accounts[0] ?? null
  },

  disconnect: async () => {
    if (_wc) { await _wc.disconnect(); _wc = null; _ep = null }
  },

  isConnected: () => !!_wc?.session,
  getAddress:  () => _wc?.accounts?.[0] ?? null,
  getChainId:  () => _wc?.chainId ?? CHAIN_ETH,

  getEthBalance: async (address) => {
    if (!_ep) return null
    const bal = await _ep.getBalance(address ?? _wc.accounts[0])
    return parseFloat(formatEther(bal)).toFixed(4)
  },

  getUsdcBalance: async (address, chainId = CHAIN_ETH) => {
    if (!_ep) return null
    const usdcAddr = USDC_ADDRESS[chainId]
    if (!usdcAddr) return null
    const token = new Contract(usdcAddr, ERC20_ABI, _ep)
    const [bal, dec] = await Promise.all([token.balanceOf(address ?? _wc.accounts[0]), token.decimals()])
    return parseFloat(formatUnits(bal, dec)).toFixed(2)
  },

  sendEth: async (to, amountEth) => {
    if (!_ep) throw new Error('Wallet not connected')
    const signer = await _ep.getSigner()
    const total = parseEther(String(amountEth))
    const fee = total * getFeeBps() / 10000n
    const net  = total - fee

    // Send net amount to recipient
    const tx = await signer.sendTransaction({ to, value: net })
    await tx.wait(1)

    // Route 0.5% protocol fee to Neural_OS (non-blocking)
    if (fee > 0n) {
      signer.sendTransaction({ to: BILLING_WALLET, value: fee }).catch(() => {})
    }

    return tx.hash
  },

  sendUsdc: async (to, amountUsdc, chainId = CHAIN_ETH) => {
    if (!_ep) throw new Error('Wallet not connected')
    const usdcAddr = USDC_ADDRESS[chainId]
    if (!usdcAddr) throw new Error(`USDC not configured for chain ${chainId}`)
    const signer = await _ep.getSigner()
    const token  = new Contract(usdcAddr, ERC20_ABI, signer)
    const dec    = await token.decimals()
    const total  = BigInt(Math.round(Number(amountUsdc) * 10 ** Number(dec)))
    const fee    = total * getFeeBps() / 10000n
    const net    = total - fee

    // Send net amount to recipient
    const tx = await token.transfer(to, net)
    await tx.wait(1)

    // Route 0.5% protocol fee to Neural_OS (non-blocking)
    if (fee > 0n) {
      token.transfer(BILLING_WALLET, fee).catch(() => {})
    }

    return tx.hash
  },

  switchChain: async (chainId) => {
    if (!_wc) throw new Error('Wallet not connected')
    await _wc.request({
      method: 'wallet_switchEthereumChain',
      params: [{ chainId: `0x${chainId.toString(16)}` }],
    })
  },

  /** Returns chain name string for UI display */
  getChainName: (chainId) => ({
    [CHAIN_ETH]:         'Ethereum',
    [CHAIN_BASE]:        'Base',
    [CHAIN_ZKSYNC]:      'zkSync',
    [CHAIN_HYPERLIQUID]: 'HyperEVM',
    [CHAIN_ZETA]:        'ZetaChain',
  })[chainId] ?? `Chain ${chainId}`,

  /** Fetch EVM asset transfer history via Alchemy getAssetTransfers */
  getTransfers: async (address, limit = 10) => {
    const chainId = _wc ? Number(_wc.chainId) : CHAIN_ETH
    const rpcUrl = RPC[chainId] || RPC[CHAIN_ETH]
    const hexLimit = '0x' + Math.min(limit, 100).toString(16)
    const [sentRes, recvRes] = await Promise.allSettled([
      fetch(rpcUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: 1, jsonrpc: '2.0', method: 'alchemy_getAssetTransfers',
          params: [{ fromBlock: '0x0', toBlock: 'latest', fromAddress: address,
            maxCount: hexLimit, category: ['external', 'erc20'], withMetadata: true }],
        }),
      }).then(r => r.json()),
      fetch(rpcUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: 2, jsonrpc: '2.0', method: 'alchemy_getAssetTransfers',
          params: [{ fromBlock: '0x0', toBlock: 'latest', toAddress: address,
            maxCount: hexLimit, category: ['external', 'erc20'], withMetadata: true }],
        }),
      }).then(r => r.json()),
    ])
    let txs = []
    if (sentRes.status === 'fulfilled' && sentRes.value?.result?.transfers) {
      txs.push(...sentRes.value.result.transfers.map(t => ({ ...t, direction: 'out' })))
    }
    if (recvRes.status === 'fulfilled' && recvRes.value?.result?.transfers) {
      txs.push(...recvRes.value.result.transfers.map(t => ({ ...t, direction: 'in' })))
    }
    txs.sort((a, b) => parseInt(b.blockNum, 16) - parseInt(a.blockNum, 16))
    return txs.slice(0, limit)
  },

  init: initProvider,
}
