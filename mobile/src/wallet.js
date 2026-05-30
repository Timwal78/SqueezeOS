import { EthereumProvider } from '@walletconnect/ethereum-provider'
import { BrowserProvider, formatEther, parseEther, Contract, formatUnits } from 'ethers'
import { WC_PROJECT_ID, RPC, CHAIN_ETH, CHAIN_BASE, USDC_ADDRESS } from './config.js'

const ERC20_ABI = [
  'function balanceOf(address owner) view returns (uint256)',
  'function decimals() view returns (uint8)',
  'function symbol() view returns (string)',
  'function transfer(address to, uint256 amount) returns (bool)',
  'function allowance(address owner, address spender) view returns (uint256)',
  'function approve(address spender, uint256 amount) returns (bool)',
]

let _wc   = null   // EthereumProvider instance
let _ep   = null   // BrowserProvider (ethers)

async function initProvider() {
  if (_wc) return _wc

  _wc = await EthereumProvider.init({
    projectId: WC_PROJECT_ID,
    chains: [CHAIN_ETH],
    optionalChains: [CHAIN_BASE],
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

  // Reconnect existing session silently
  if (_wc.session) {
    _ep = new BrowserProvider(_wc)
  }

  return _wc
}

export const Wallet = {
  /** Open WalletConnect modal and connect */
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

  /** Returns ETH balance as formatted string e.g. "1.2345" */
  getEthBalance: async (address) => {
    if (!_ep) return null
    const bal = await _ep.getBalance(address ?? _wc.accounts[0])
    return parseFloat(formatEther(bal)).toFixed(4)
  },

  /** Returns USDC balance as formatted string e.g. "120.00" */
  getUsdcBalance: async (address, chainId = CHAIN_ETH) => {
    if (!_ep) return null
    const token = new Contract(USDC_ADDRESS[chainId], ERC20_ABI, _ep)
    const [bal, dec] = await Promise.all([token.balanceOf(address ?? _wc.accounts[0]), token.decimals()])
    return parseFloat(formatUnits(bal, dec)).toFixed(2)
  },

  /** Send native ETH.  Returns tx hash. */
  sendEth: async (to, amountEth) => {
    if (!_ep) throw new Error('Wallet not connected')
    const signer = await _ep.getSigner()
    const tx = await signer.sendTransaction({ to, value: parseEther(String(amountEth)) })
    await tx.wait(1)
    return tx.hash
  },

  /** Send USDC ERC-20.  Returns tx hash. */
  sendUsdc: async (to, amountUsdc, chainId = CHAIN_ETH) => {
    if (!_ep) throw new Error('Wallet not connected')
    const signer = await _ep.getSigner()
    const token = new Contract(USDC_ADDRESS[chainId], ERC20_ABI, signer)
    const dec = await token.decimals()
    const amount = BigInt(Math.round(Number(amountUsdc) * 10 ** Number(dec)))
    const tx = await token.transfer(to, amount)
    await tx.wait(1)
    return tx.hash
  },

  /** Switch the connected wallet to a different chain */
  switchChain: async (chainId) => {
    if (!_wc) throw new Error('Wallet not connected')
    await _wc.request({
      method: 'wallet_switchEthereumChain',
      params: [{ chainId: `0x${chainId.toString(16)}` }],
    })
  },

  /** Pre-warm the provider (call on every page load) */
  init: initProvider,
}
